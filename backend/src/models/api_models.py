from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime


# ── Recording ─────────────────────────────────────────────────────────────────

class StartRecordingRequest(BaseModel):
    url: str

class WorkflowResponse(BaseModel):
    workflow_id: int
    name: str
    url: str
    created_at: Optional[datetime] = None
    class Config:
        from_attributes = True


# ── Action capture (sent by content script) ───────────────────────────────────

class RecordActionRequest(BaseModel):
    workflow_id: int
    action: str            # click | type | navigate | select | scroll
    selector: Optional[str] = None   # CSS selector of the element
    element_type: Optional[str] = None
    element_text: Optional[str] = None
    value: Optional[str] = None      # typed text, href, selected option
    url: str                          # page URL where action happened
    attributes: Optional[dict] = None


class StopRecordingRequest(BaseModel):
    workflow_id: int


# ── Steps / Replay ────────────────────────────────────────────────────────────

class WorkflowStepOut(BaseModel):
    id: int
    step_order: int
    action: str
    selector: Optional[str] = None
    value: Optional[str] = None
    url: Optional[str] = None
    element_type: Optional[str] = None
    element_text: Optional[str] = None
    class Config:
        from_attributes = True


class WorkflowDetail(BaseModel):
    workflow_id: int
    name: str
    url: str
    created_at: Optional[datetime] = None
    steps: List[WorkflowStepOut] = []
    class Config:
        from_attributes = True


class ReplayRequest(BaseModel):
    workflow_id: int


class ReplayStepResult(BaseModel):
    step_order: int
    action: str
    selector: Optional[str]
    value: Optional[str]
    status: str          # success | failed | skipped
    error: Optional[str] = None


class ReplayResponse(BaseModel):
    workflow_id: int
    status: str          # completed | partial | failed
    steps: List[ReplayStepResult]


class TestCaseStep(BaseModel):
    element_id: str
    action: str
    value: Optional[str] = None


class TestCaseAssertion(BaseModel):
    type: str
    expected: str


class TestCase(BaseModel):
    name: str
    category: str
    steps: List[TestCaseStep]
    assertions: List[TestCaseAssertion]
    confidence: float


class GenerateTestsRequest(BaseModel):
    instructions: Optional[str] = None


class GenerateTestsResponse(BaseModel):
    workflow_id: int
    test_cases: List[TestCase]


class SetupStatusResponse(BaseModel):
    database: str
    groq_configured: bool
    gemini_configured: bool


# ── Test Case Replay ──────────────────────────────────────────────────────────

class ReplayTestCaseRequest(BaseModel):
    test_case_index: int  # index of the test case in the workflow's test_cases list


class AssertionResult(BaseModel):
    type: str
    expected: str
    passed: bool
    message: Optional[str] = None


class ReplayTestCaseStepResult(BaseModel):
    step_index: int
    element_id: str
    action: str
    value: Optional[str] = None
    status: str           # success | failed | skipped
    error: Optional[str] = None


class ReplayTestCaseResponse(BaseModel):
    workflow_id: int
    test_case_name: str
    test_case_category: str
    status: str           # passed | failed | error
    steps: List[ReplayTestCaseStepResult]
    assertions: List[AssertionResult]
    duration_ms: Optional[int] = None
    screenshot_b64: Optional[str] = None  # base64 PNG taken after replay
