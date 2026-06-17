import json
import traceback
from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..models.api_models import (
    StartRecordingRequest, WorkflowResponse,
    RecordActionRequest, StopRecordingRequest,
    WorkflowDetail, WorkflowStepOut,

)
from ..services.browser_service import BrowserService, ReplayService
from ..database.connection import get_db
from ..database.models import Workflow, WorkflowStep, Element, Page
from ..utils.dom_parser import DOMParser

router = APIRouter()


def get_browser_service() -> BrowserService:
    return BrowserService()

def get_replay_service() -> ReplayService:
    return ReplayService()


# ── 1. Start a new workflow (creates the DB record) ───────────────────────────

@router.post("/record/start", response_model=WorkflowResponse)
async def start_recording(
    request: StartRecordingRequest,
    db: Session = Depends(get_db),
    browser_service: BrowserService = Depends(get_browser_service),
):
    try:
        result = await browser_service.get_page_content(request.url)
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(500, detail=f"Browser error: {type(e).__name__}: {e}")

    try:
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        title = result.get("title") or request.url
        workflow = Workflow(
            name=f"{title} [{ts}]",
            url=request.url,
        )
        db.add(workflow)
        db.commit()
        db.refresh(workflow)
        return WorkflowResponse(
            workflow_id=workflow.id,
            name=workflow.name,
            url=workflow.url,
            created_at=workflow.created_at,
        )
    except Exception as e:
        traceback.print_exc()
        db.rollback()
        raise HTTPException(500, detail=f"DB error: {type(e).__name__}: {e}")


# ── 2. Record one action (called by content script on every user action) ──────

@router.post("/record/action")
async def record_action(
    request: RecordActionRequest,
    db: Session = Depends(get_db),
):
    workflow = db.query(Workflow).filter(Workflow.id == request.workflow_id).first()
    if not workflow:
        raise HTTPException(404, detail="Workflow not found")

    try:
        # Upsert the Page
        page = db.query(Page).filter(Page.url == request.url[:768]).first()
        if not page:
            page = Page(url=request.url[:768])
            db.add(page)
            db.flush()

        # Create / reuse Element
        element = None
        if request.selector:
            element = Element(
                page_id=page.id,
                element_type=request.element_type or "unknown",
                text=request.element_text,
                selector=request.selector,
                attributes=json.dumps(request.attributes or {}),
            )
            db.add(element)
            db.flush()

        # Determine next step order
        last = (
            db.query(WorkflowStep)
            .filter(WorkflowStep.workflow_id == request.workflow_id)
            .order_by(WorkflowStep.step_order.desc())
            .first()
        )
        next_order = (last.step_order + 1) if last else 1

        step = WorkflowStep(
            workflow_id=request.workflow_id,
            element_id=element.id if element else None,
            step_order=next_order,
            action=request.action,
            value=request.value,
            selector=request.selector,
            url=request.url,
        )
        db.add(step)
        db.commit()

        return {"status": "ok", "step_order": next_order}

    except Exception as e:
        traceback.print_exc()
        db.rollback()
        raise HTTPException(500, detail=f"{type(e).__name__}: {e}")


# ── 3. Stop recording ─────────────────────────────────────────────────────────

@router.post("/record/stop")
async def stop_recording(
    request: StopRecordingRequest,
    db: Session = Depends(get_db),
):
    workflow = db.query(Workflow).filter(Workflow.id == request.workflow_id).first()
    if not workflow:
        raise HTTPException(404, detail="Workflow not found")

    step_count = (
        db.query(WorkflowStep)
        .filter(WorkflowStep.workflow_id == request.workflow_id)
        .count()
    )
    return {"status": "stopped", "workflow_id": request.workflow_id, "steps_recorded": step_count}


# ── 4. List all workflows ─────────────────────────────────────────────────────

@router.get("/workflows", response_model=List[WorkflowResponse])
def list_workflows(db: Session = Depends(get_db)):
    workflows = db.query(Workflow).order_by(Workflow.created_at.desc()).all()
    return [
        WorkflowResponse(
            workflow_id=wf.id,
            name=wf.name,
            url=wf.url,
            created_at=wf.created_at,
        )
        for wf in workflows
    ]


# ── 5. Delete all workflows (must be before /workflows/{workflow_id}) ─────────

@router.delete("/workflows/clear_all")
def clear_all_workflows(db: Session = Depends(get_db)):
    # Delete WorkflowStep records first due to foreign key constraints
    db.query(WorkflowStep).delete()
    # Delete Element records
    db.query(Element).delete()
    # Delete Page records
    db.query(Page).delete()
    # Delete Workflow records
    db.query(Workflow).delete()
    db.commit()
    return {"status": "all workflows cleared"}


# ── 6. Get workflow detail (with steps) ───────────────────────────────────────

@router.get("/workflows/{workflow_id}", response_model=WorkflowDetail)
def get_workflow(workflow_id: int, db: Session = Depends(get_db)):
    wf = db.query(Workflow).filter(Workflow.id == workflow_id).first()
    if not wf:
        raise HTTPException(404, detail="Workflow not found")

    steps_out = []
    for s in wf.steps:
        el_text = None
        el_type = None
        if s.element:
            el_text = s.element.text
            el_type = s.element.element_type
        steps_out.append(WorkflowStepOut(
            id=s.id,
            step_order=s.step_order,
            action=s.action,
            selector=s.selector,
            value=s.value,
            url=s.url,
            element_type=el_type,
            element_text=el_text,
        ))

    return WorkflowDetail(
        workflow_id=wf.id,
        name=wf.name,
        url=wf.url,
        created_at=wf.created_at,
        steps=steps_out,
    )


# ── 6. Replay a workflow ──────────────────────────────────────────────────────

@router.post("/workflows/{workflow_id}/replay", response_model=List[WorkflowStepOut])
async def replay_workflow(workflow_id: int, db: Session = Depends(get_db)):
    wf = db.query(Workflow).filter(Workflow.id == workflow_id).first()
    if not wf:
        raise HTTPException(404, detail="Workflow not found")

    steps_out = []
    for s in wf.steps:
        el_text = None
        el_type = None
        if s.element:
            el_text = s.element.text
            el_type = s.element.element_type
        steps_out.append(
            WorkflowStepOut(
                id=s.id,
                step_order=s.step_order,
                action=s.action,
                selector=s.selector,
                value=s.value,
                url=s.url,
                element_type=el_type,
                element_text=el_text,
            )
        )
    return steps_out


# ── 7. Delete a workflow ──────────────────────────────────────────────────────

@router.delete("/workflows/{workflow_id}")
def delete_workflow(workflow_id: int, db: Session = Depends(get_db)):
    wf = db.query(Workflow).filter(Workflow.id == workflow_id).first()
    if not wf:
        raise HTTPException(404, detail="Workflow not found")
    db.delete(wf)
    db.commit()
    return {"status": "deleted", "workflow_id": workflow_id}


# ── 8. Delete all workflows ───────────────────────────────────────────────────

@router.delete("/workflows/clear_all")
def clear_all_workflows(db: Session = Depends(get_db)):
    # Delete WorkflowStep records first due to foreign key constraints
    db.query(WorkflowStep).delete()
    # Delete Element records
    db.query(Element).delete()
    # Delete Page records
    db.query(Page).delete()
    # Delete Workflow records
    db.query(Workflow).delete()
    db.commit()
    return {"status": "all workflows cleared"}