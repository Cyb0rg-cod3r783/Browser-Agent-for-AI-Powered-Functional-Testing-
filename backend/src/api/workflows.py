import json
import traceback
from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException

from ..models.api_models import (
    StartRecordingRequest, WorkflowResponse,
    RecordActionRequest, StopRecordingRequest,
    WorkflowDetail, WorkflowStepOut,
    TestCase, GenerateTestsResponse
)
from ..services.browser_service import BrowserService, ReplayService
from ..services.llm_service import llm_service
from ..database.json_db import json_db

router = APIRouter()


def get_browser_service() -> BrowserService:
    return BrowserService()

def get_replay_service() -> ReplayService:
    return ReplayService()


# ── 1. Start a new workflow (creates the JSON record) ───────────────────────────

@router.post("/record/start", response_model=WorkflowResponse)
async def start_recording(
    request: StartRecordingRequest,
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
        workflow = json_db.create_workflow(
            name=f"{title} [{ts}]",
            url=request.url
        )
        return WorkflowResponse(
            workflow_id=workflow["id"],
            name=workflow["name"],
            url=workflow["url"],
            created_at=datetime.fromisoformat(workflow["created_at"])
        )
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(500, detail=f"DB error: {type(e).__name__}: {e}")


# ── 2. Record one action (called by content script on every user action) ──────

@router.post("/record/action")
async def record_action(
    request: RecordActionRequest,
):
    workflow = json_db.get_workflow(request.workflow_id)
    if not workflow:
        raise HTTPException(404, detail="Workflow not found")

    try:
        # Upsert Page
        page = json_db.get_or_create_page(request.url)

        # Create Element
        element = None
        if request.selector:
            element = json_db.create_element(
                page_id=page["id"],
                element_type=request.element_type or "unknown",
                text=request.element_text,
                selector=request.selector,
                attributes=request.attributes or {}
            )

        step = json_db.add_workflow_step(
            workflow_id=request.workflow_id,
            element_id=element["id"] if element else None,
            action=request.action,
            value=request.value,
            selector=request.selector,
            url=request.url
        )

        return {"status": "ok", "step_order": step["step_order"]}

    except Exception as e:
        traceback.print_exc()
        raise HTTPException(500, detail=f"{type(e).__name__}: {e}")


# ── 3. Stop recording ─────────────────────────────────────────────────────────

@router.post("/record/stop")
async def stop_recording(
    request: StopRecordingRequest,
):
    workflow = json_db.get_workflow(request.workflow_id)
    if not workflow:
        raise HTTPException(404, detail="Workflow not found")

    step_count = json_db.count_workflow_steps(request.workflow_id)
    return {"status": "stopped", "workflow_id": request.workflow_id, "steps_recorded": step_count}


# ── 4. List all workflows ─────────────────────────────────────────────────────

@router.get("/workflows", response_model=List[WorkflowResponse])
def list_workflows():
    workflows = json_db.get_workflows()
    return [
        WorkflowResponse(
            workflow_id=wf["id"],
            name=wf["name"],
            url=wf["url"],
            created_at=datetime.fromisoformat(wf["created_at"]) if wf.get("created_at") else None,
        )
        for wf in workflows
    ]


# ── 5. Clear all workflows ───────────────────────────────────────────────────

@router.delete("/workflows/clear_all")
def clear_all_workflows():
    json_db.clear_all()
    return {"status": "all workflows cleared"}


# ── 6. Get workflow detail (with steps) ───────────────────────────────────────

@router.get("/workflows/{workflow_id}", response_model=WorkflowDetail)
def get_workflow(workflow_id: int):
    wf = json_db.get_workflow(workflow_id)
    if not wf:
        raise HTTPException(404, detail="Workflow not found")

    steps_out = []
    for s in wf.get("steps", []):
        el_text = None
        el_type = None
        if s.get("element"):
            el_text = s["element"].get("text")
            el_type = s["element"].get("element_type")
        steps_out.append(WorkflowStepOut(
            id=s["id"],
            step_order=s["step_order"],
            action=s["action"],
            selector=s.get("selector"),
            value=s.get("value"),
            url=s.get("url"),
            element_type=el_type,
            element_text=el_text,
        ))

    return WorkflowDetail(
        workflow_id=wf["id"],
        name=wf["name"],
        url=wf["url"],
        created_at=datetime.fromisoformat(wf["created_at"]) if wf.get("created_at") else None,
        steps=steps_out,
    )


# ── 7. Replay a workflow ──────────────────────────────────────────────────────

@router.post("/workflows/{workflow_id}/replay", response_model=List[WorkflowStepOut])
async def replay_workflow(workflow_id: int):
    wf = json_db.get_workflow(workflow_id)
    if not wf:
        raise HTTPException(404, detail="Workflow not found")

    steps_out = []
    for s in wf.get("steps", []):
        el_text = None
        el_type = None
        if s.get("element"):
            el_text = s["element"].get("text")
            el_type = s["element"].get("element_type")
        steps_out.append(
            WorkflowStepOut(
                id=s["id"],
                step_order=s["step_order"],
                action=s["action"],
                selector=s.get("selector"),
                value=s.get("value"),
                url=s.get("url"),
                element_type=el_type,
                element_text=el_text,
            )
        )
    return steps_out


# ── 8. Delete a workflow ──────────────────────────────────────────────────────

@router.delete("/workflows/{workflow_id}")
def delete_workflow(workflow_id: int):
    success = json_db.delete_workflow(workflow_id)
    if not success:
        raise HTTPException(404, detail="Workflow not found")
    return {"status": "deleted", "workflow_id": workflow_id}


# ── 9. Generate AI-powered test cases from workflow ──────────────────────────

@router.post("/workflows/{workflow_id}/generate_tests", response_model=GenerateTestsResponse)
async def generate_workflow_tests(
    workflow_id: int,
    browser_service: BrowserService = Depends(get_browser_service)
):
    workflow = json_db.get_workflow(workflow_id)
    if not workflow:
        raise HTTPException(404, detail="Workflow not found")

    # 1. Fetch accessibility snapshot and elements using Playwright
    try:
        page_info = await browser_service.get_accessibility_and_elements(workflow["url"])
    except Exception as e:
        raise HTTPException(500, detail=f"Failed to analyze page with Playwright: {e}")

    # 2. Query LLM to label elements
    labeled_elements = []
    for el in page_info.get("elements", []):
        # Format elements properties to match the expected ELEMENT_LABEL_PROMPT variables
        element_payload = {
            "tag": el.get("tag", "input"),
            "input_type": el.get("input_type", "text"),
            "element_id": el.get("element_id", ""),
            "name": el.get("name", ""),
            "placeholder": el.get("placeholder", ""),
            "aria_label": el.get("aria_label", ""),
            "label_text": el.get("label_text", ""),
            "context": el.get("context", "")
        }
        labeled = await llm_service.label_element(element_payload)
        labeled_elements.append({
            "element_id": el.get("element_id") or el.get("name") or el.get("placeholder") or "field",
            "semantic_label": labeled.get("semantic_label"),
            "purpose": labeled.get("purpose"),
            "validation_rules": labeled.get("validation_rules"),
            "stable_locator_ranking": labeled.get("stable_locator_ranking")
        })

    # 3. Generate test cases using LLM
    observed_steps = []
    for s in workflow.get("steps", []):
        observed_steps.append({
            "action": s.get("action"),
            "selector": s.get("selector"),
            "value": s.get("value")
        })

    expected_outcome = "Page loaded and user action completed successfully."
    test_suite = await llm_service.generate_test_cases(
        flow_name=workflow["name"],
        start_url=workflow["url"],
        steps=observed_steps,
        elements=labeled_elements,
        expected_outcome=expected_outcome
    )

    test_cases = test_suite.get("test_cases", [])

    # 4. Save test cases in database
    json_db.save_test_cases(workflow_id, test_cases)

    return GenerateTestsResponse(workflow_id=workflow_id, test_cases=test_cases)


# ── 10. Get previously generated test cases ───────────────────────────────────

@router.get("/workflows/{workflow_id}/test_cases", response_model=List[TestCase])
async def get_workflow_test_cases(workflow_id: int):
    workflow = json_db.get_workflow(workflow_id)
    if not workflow:
        raise HTTPException(404, detail="Workflow not found")
    return workflow.get("test_cases", [])