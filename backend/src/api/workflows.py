import json
import re
import asyncio
import traceback
from datetime import datetime
from typing import List
from fastapi import APIRouter, Depends, HTTPException, Body

from ..models.api_models import (
    StartRecordingRequest, WorkflowResponse,
    RecordActionRequest, StopRecordingRequest,
    WorkflowDetail, WorkflowStepOut,
    TestCase, GenerateTestsResponse, GenerateTestsRequest, SetupStatusResponse,
    ReplayResponse, ReplayStepResult,
    ReplayTestCaseRequest, ReplayTestCaseResponse,
    ReplayTestCaseStepResult, AssertionResult
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
    try:
        json_db.clear_all()
        return {"message": "All workflows cleared."}
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(500, detail=f"Failed to clear workflows: {e}")

@router.get("/setup/status", response_model=SetupStatusResponse)
async def get_setup_status():
    from ..core.config import settings
    return SetupStatusResponse(
        database="MySQL" if "mysql" in (settings.DATABASE_URL or "") else "SQLite/JSON",
        groq_configured=bool(settings.GROQ_API_KEY),
        gemini_configured=bool(settings.GEMINI_API_KEY)
    )


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

@router.post("/workflows/{workflow_id}/replay", response_model=ReplayResponse)
async def replay_workflow(
    workflow_id: int,
    replay_service: ReplayService = Depends(get_replay_service)
):
    wf = json_db.get_workflow(workflow_id)
    if not wf:
        raise HTTPException(404, detail="Workflow not found")

    steps = wf.get("steps", [])
    if not steps:
        return ReplayResponse(workflow_id=workflow_id, status="completed", steps=[])

    try:
        # Replay the steps using server-side Playwright
        step_results = await replay_service.replay(wf["url"], steps)
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(500, detail=f"Replay execution failed: {e}")

    # Determine overall status based on step outcomes
    success_count = sum(1 for r in step_results if r.get("status") == "success")
    failed_count = sum(1 for r in step_results if r.get("status") == "failed")
    
    if failed_count > 0:
        if success_count > 0:
            overall_status = "partial"
        else:
            overall_status = "failed"
    else:
        overall_status = "completed"

    # Format into ReplayStepResult schema
    formatted_steps = []
    for r in step_results:
        formatted_steps.append(ReplayStepResult(
            step_order=r["step_order"],
            action=r["action"],
            selector=r.get("selector"),
            value=r.get("value"),
            status=r["status"],
            error=r.get("error")
        ))

    return ReplayResponse(
        workflow_id=workflow_id,
        status=overall_status,
        steps=formatted_steps
    )



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
    request: GenerateTestsRequest = Body(default=GenerateTestsRequest()),
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

    # 3. Build steps list from recording
    steps = []
    for s in workflow.get("steps", []):
        steps.append({
            "action": s.get("action"),
            "selector": s.get("selector"),
            "value": s.get("value")
        })

    # 4. Extract what the user actually typed during recording
    #    Map: selector → { value, inferred_type }
    recorded_values: dict = {}
    for s in workflow.get("steps", []):
        if s.get("action") in ("fill", "type") and s.get("value"):
            sel   = s.get("selector") or ""
            val   = s.get("value", "")
            eid   = s.get("element_id") or sel

            # Infer field type from the recorded value
            import re as _re
            if _re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', val):
                inferred = "email"
            elif len(val) >= 6 and any(c.isupper() for c in val) and any(c.isdigit() for c in val):
                inferred = "password"
            elif val.replace("+","").replace("-","").replace(" ","").replace("(","").replace(")","").isdigit() and len(val) >= 7:
                inferred = "phone"
            elif val.isdigit():
                inferred = "number"
            elif _re.match(r'^\d{4}-\d{2}-\d{2}$', val):
                inferred = "date"
            elif val.startswith("http"):
                inferred = "url"
            else:
                inferred = "text"

            recorded_values[eid] = {"value": val, "inferred_type": inferred}

    # 5. Build enriched elements — merge page elements with recorded values
    enriched_elements = []
    raw_elements = page_info.get("elements", [])
    for i, labeled in enumerate(labeled_elements):
        raw = raw_elements[i] if i < len(raw_elements) else {}
        eid = labeled.get("element_id") or raw.get("element_id") or raw.get("name") or ""

        # Look up if user typed something into this element during recording
        recorded = recorded_values.get(eid) or recorded_values.get(f"#{eid}") or \
                   recorded_values.get(f"[name='{eid}']") or {}

        enriched_elements.append({
            **labeled,
            "tag":          raw.get("tag", "input"),
            "input_type":   raw.get("input_type", "text"),
            "name":         raw.get("name", ""),
            "placeholder":  raw.get("placeholder", ""),
            # Key addition: what the user actually typed + inferred type
            "recorded_value":         recorded.get("value"),
            "recorded_value_type":    recorded.get("inferred_type"),
        })

    # Generate test cases with LLM
    try:
        test_suite = await llm_service.generate_test_cases(
            flow_name=workflow["name"],
            start_url=workflow["url"],
            steps=steps,
            elements=enriched_elements,
            expected_outcome="User successfully completed the flow.",
            instructions=request.instructions
        )
    except Exception as e:
        raise HTTPException(500, detail=f"Failed to generate tests: {e}")

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


# ── 12. Run all test cases — parallel batches with per-test timeout ──────────

BATCH_SIZE    = 5   # run 5 tests simultaneously
TEST_TIMEOUT  = 30  # seconds per individual test before it's marked "timeout"

def _build_replay_steps(tc: dict, start_url: str) -> list:
    """Convert AI test case steps into Playwright replay step dicts."""
    action_map = {"fill": "fill", "click": "click", "check": "check",
                  "select": "select", "navigate": "navigate"}
    replay_steps = []
    for i, step in enumerate(tc.get("steps", [])):
        action = action_map.get(step["action"], step["action"])
        eid    = step["element_id"]
        if action == "navigate":
            selector = None
        elif re.search(r'[#\.\[\]>:\s]', eid) or eid.lower() in ("html", "body"):
            selector = eid
        else:
            safe = eid.replace("'", "\\'")
            selector = (
                f"#{safe}, [name='{safe}'], [placeholder='{safe}'], "
                f"[value='{safe}'], input[type='submit'], button[type='submit'], button"
            )
        replay_steps.append({
            "step_order": i + 1, "action": action,
            "selector": selector, "value": step.get("value"),
            "url": start_url, "element_id": eid,
        })
    return replay_steps


async def _run_one(idx: int, tc: dict, start_url: str,
                   replay_service: ReplayService) -> dict:
    """Run a single test case with a timeout."""
    replay_steps = _build_replay_steps(tc, start_url)
    start = datetime.utcnow()
    try:
        raw = await asyncio.wait_for(
            replay_service.replay_test_case(start_url, replay_steps, tc.get("assertions", [])),
            timeout=TEST_TIMEOUT,
        )
    except asyncio.TimeoutError:
        return {
            "index": idx, "name": tc["name"], "category": tc["category"],
            "status": "failed", "duration_ms": TEST_TIMEOUT * 1000,
            "steps": [], "assertions": [],
            "screenshot_b64": None,
            "error": f"Test timed out after {TEST_TIMEOUT}s",
        }
    except Exception as e:
        return {
            "index": idx, "name": tc["name"], "category": tc["category"],
            "status": "error", "duration_ms": 0,
            "steps": [], "assertions": [],
            "screenshot_b64": None,
            "error": str(e),
        }

    duration_ms = int((datetime.utcnow() - start).total_seconds() * 1000)
    has_failure = any(r["status"] == "failed" for r in raw.get("step_results", []))
    tc_category = tc.get("category", "happy_path")
    ar_list     = raw.get("assertion_results", [])

    if ar_list:
        assertions_passed = all(a["passed"] for a in ar_list)
        if tc_category == "happy_path":
            status = "passed" if (not has_failure and assertions_passed) else "failed"
        else:
            status = "passed" if assertions_passed else "failed"
    else:
        status = "passed" if not has_failure else "failed"

    return {
        "index": idx, "name": tc["name"], "category": tc["category"],
        "status": status, "duration_ms": duration_ms,
        "steps": raw.get("step_results", []),
        "assertions": raw.get("assertion_results", []),
        "screenshot_b64": raw.get("screenshot_b64"),
    }


@router.post("/workflows/{workflow_id}/run_all_tests")
async def run_all_tests(
    workflow_id: int,
    replay_service: ReplayService = Depends(get_replay_service),
):
    wf = json_db.get_workflow(workflow_id)
    if not wf:
        raise HTTPException(404, detail="Workflow not found")

    test_cases = wf.get("test_cases", [])
    if not test_cases:
        raise HTTPException(400, detail="No test cases generated yet.")

    results = []

    # Process in batches of BATCH_SIZE concurrently
    for batch_start in range(0, len(test_cases), BATCH_SIZE):
        batch = list(enumerate(test_cases))[batch_start : batch_start + BATCH_SIZE]
        batch_results = await asyncio.gather(*[
            _run_one(idx, tc, wf["url"], replay_service)
            for idx, tc in batch
        ])
        results.extend(batch_results)
        print(f"[RunAll] Batch {batch_start // BATCH_SIZE + 1} done "
              f"({batch_start + len(batch)}/{len(test_cases)})")

    total  = len(results)
    passed = sum(1 for r in results if r["status"] == "passed")
    failed = total - passed
    return {
        "workflow_id": workflow_id,
        "total": total, "passed": passed, "failed": failed,
        "results": results,
    }

@router.post("/workflows/{workflow_id}/replay_test_case", response_model=ReplayTestCaseResponse)
async def replay_test_case(
    workflow_id: int,
    request: ReplayTestCaseRequest,
    replay_service: ReplayService = Depends(get_replay_service),
):
    wf = json_db.get_workflow(workflow_id)
    if not wf:
        raise HTTPException(404, detail="Workflow not found")

    test_cases = wf.get("test_cases", [])
    if request.test_case_index < 0 or request.test_case_index >= len(test_cases):
        raise HTTPException(400, detail="Invalid test case index")

    test_case = test_cases[request.test_case_index]

    # Build Playwright steps from AI test case steps
    action_map = {"fill": "fill", "click": "click", "check": "check",
                  "select": "select", "navigate": "navigate"}

    replay_steps = []
    for i, step in enumerate(test_case.get("steps", [])):
        action = action_map.get(step["action"], step["action"])
        eid = step["element_id"]

        if action == "navigate":
            selector = None
        elif re.search(r'[#\.\[\]>:\s]', eid) or eid.lower() in ("html", "body"):
            selector = eid
        else:
            safe = eid.replace("'", "\\'")
            # Comprehensive fallback: id, name, placeholder, value attr, button text, input[type=submit]
            selector = (
                f"#{safe}, "
                f"[name='{safe}'], "
                f"[placeholder='{safe}'], "
                f"[value='{safe}'], "
                f"input[type='submit'], "
                f"button[type='submit'], "
                f"button"
            )

        replay_steps.append({
            "step_order": i + 1,
            "action": action,
            "selector": selector,
            "value": step.get("value"),
            "url": wf["url"],
            "element_id": eid,
        })

    assertions = test_case.get("assertions", [])

    start_time = datetime.utcnow()
    try:
        raw = await replay_service.replay_test_case(wf["url"], replay_steps, assertions)
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(500, detail=f"Replay execution failed: {e}")
    end_time = datetime.utcnow()
    duration_ms = int((end_time - start_time).total_seconds() * 1000)

    step_results = raw.get("step_results", [])
    assertion_results = raw.get("assertion_results", [])

    formatted_steps = []
    has_step_failure = False
    for r, orig in zip(step_results, replay_steps):
        if r["status"] == "failed":
            has_step_failure = True
        formatted_steps.append(ReplayTestCaseStepResult(
            step_index=r["step_order"] - 1,
            element_id=orig["element_id"],
            action=orig["action"],
            value=r.get("value"),
            status=r["status"],
            error=r.get("error"),
        ))

    formatted_assertions = [
        AssertionResult(
            type=ar["type"],
            expected=ar["expected"],
            passed=ar["passed"],
            message=ar.get("message", ""),
        )
        for ar in assertion_results
    ]

    category = test_case.get("category", "happy_path")

    if assertion_results:
        # Assertions are always the source of truth
        assertions_passed = all(ar["passed"] for ar in assertion_results)
        if category == "happy_path":
            # Happy path: steps must all succeed AND assertions must pass
            status = "passed" if (not has_step_failure and assertions_passed) else "failed"
        else:
            # Negative / edge / security: assertions decide pass/fail.
            # A step "failing" (e.g. submit button not found) is expected and acceptable —
            # what matters is whether the page behaved correctly (stayed on page, showed error, etc.)
            status = "passed" if assertions_passed else "failed"
    else:
        # No assertions defined — fall back to step results
        status = "passed" if not has_step_failure else "failed"

    return ReplayTestCaseResponse(
        workflow_id=workflow_id,
        test_case_name=test_case["name"],
        test_case_category=test_case["category"],
        status=status,
        steps=formatted_steps,
        assertions=formatted_assertions,
        duration_ms=duration_ms,
        screenshot_b64=raw.get("screenshot_b64"),
    )