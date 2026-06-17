"""
LLM Service — AI-powered test case generator.
Uses Groq (primary) → Gemini (fallback) → deterministic mock (offline fallback).
Generates comprehensive QA test suites: happy path, negative, edge cases,
boundary values, wrong data types, SQL injection, XSS, unicode, empty fields.
"""
import json
import re
import urllib.request
import urllib.error
import asyncio
from typing import Dict, Any, List
from ..core.config import settings

# ── Prompts ───────────────────────────────────────────────────────────────────

ELEMENT_LABEL_PROMPT = """
Analyze this web form element and provide a semantic label for QA test generation.

Element data:
  tag: {tag}
  type: {input_type}
  id: {element_id}
  name: {name}
  placeholder: {placeholder}
  aria_label: {aria_label}
  associated_label_text: {label_text}
  surrounding_text_context: {context}

Respond ONLY with valid JSON (no markdown, no extra text):
{{
  "semantic_label": "concise 2-6 word label",
  "field_type": "one of: email|password|name|phone|number|date|url|credit_card|text|select|checkbox|button|search",
  "purpose": "one sentence description",
  "required": true,
  "max_length": null,
  "validation_rules": [
    {{"rule": "required", "error_message": "This field is required"}},
    {{"rule": "email_format", "error_message": "Enter a valid email"}}
  ],
  "stable_locator": "best CSS selector or aria attribute to target this element"
}}
"""

TEST_GENERATION_PROMPT = """
You are a senior QA automation engineer generating a COMPREHENSIVE test suite.

## Workflow Being Tested
Flow name: {flow_name}
Start URL: {start_url}
Recorded happy-path steps:
{flow_steps_json}

## Form Elements Detected
{elements_json}

## Task
Generate a thorough test suite. You MUST include ALL of these categories:

1. **happy_path** (1 test) — reproduce exactly the recorded steps with valid data
2. **negative** (4-6 tests) — invalid inputs for each field:
   - Empty/blank required fields
   - Wrong data types (number in email field, text in number field)
   - Invalid formats (malformed email, phone without digits)
   - Strings that are too long (>255 chars)
   - SQL injection attempts: ' OR '1'='1
   - XSS payloads: <script>alert(1)</script>
3. **edge_case** (3-4 tests) — boundary and unusual inputs:
   - Minimum valid values (1 char name, minimum age)
   - Maximum valid values (very long but valid strings)
   - Unicode / international characters (日本語, Arabic, emoji 🎉)
   - Whitespace only, leading/trailing spaces
   - Special characters: !@#$%^&*()
4. **security** (2-3 tests) — security-focused:
   - SQL injection in every text field
   - XSS in every text field
   - Path traversal: ../../../etc/passwd

For EACH test case provide:
- Concrete VALUES for every field (not placeholders like "invalid_email@" — use real strings)
- Realistic assertions that a browser test would actually verify

{custom_instructions_block}

Respond ONLY with valid JSON (no markdown fences, no explanation):
{{
  "test_cases": [
    {{
      "name": "Login with valid credentials",
      "category": "happy_path",
      "description": "Verify user can log in with correct email and password",
      "steps": [
        {{"element_id": "email", "action": "fill", "value": "user@example.com"}},
        {{"element_id": "password", "action": "fill", "value": "Secure@Pass1"}},
        {{"element_id": "submit", "action": "click", "value": null}}
      ],
      "assertions": [
        {{"type": "url_contains", "expected": "/dashboard"}},
        {{"type": "element_visible", "expected": ".welcome-message"}},
        {{"type": "no_error_message", "expected": ""}}
      ],
      "confidence": 0.95
    }},
    {{
      "name": "Login with empty email",
      "category": "negative",
      "description": "Verify validation error when email is empty",
      "steps": [
        {{"element_id": "email", "action": "fill", "value": ""}},
        {{"element_id": "password", "action": "fill", "value": "Secure@Pass1"}},
        {{"element_id": "submit", "action": "click", "value": null}}
      ],
      "assertions": [
        {{"type": "error_message_present", "expected": "required"}},
        {{"type": "url_not_contains", "expected": "/dashboard"}}
      ],
      "confidence": 0.92
    }}
  ]
}}
"""

# ── Parser ────────────────────────────────────────────────────────────────────

def _extract_json(text: str) -> dict:
    """Strip markdown fences and parse the first JSON object found."""
    # Remove ```json ... ``` fences
    text = re.sub(r"```(?:json)?", "", text).strip()
    # Find outermost { }
    start = text.find("{")
    end   = text.rfind("}") + 1
    if start == -1 or end == 0:
        raise ValueError(f"No JSON object found in response: {text[:300]}")
    return json.loads(text[start:end])


class LLMService:
    def __init__(self):
        self.groq_key   = settings.GROQ_API_KEY
        self.groq_model = settings.GROQ_MODEL or "llama-3.1-8b-instant"
        self.gemini_key = settings.GEMINI_API_KEY
        self.gemini_model = "gemini-1.5-flash"

    # ── Raw API callers ───────────────────────────────────────────────────────

    def _call_groq_sync(self, prompt: str) -> str:
        if not self.groq_key:
            raise ValueError("GROQ_API_KEY not set")
        url = "https://api.groq.com/openai/v1/chat/completions"
        payload = {
            "model": self.groq_model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.15,
            "response_format": {"type": "json_object"},
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {self.groq_key}"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=45) as r:
            data = json.loads(r.read())
            return data["choices"][0]["message"]["content"]

    def _call_gemini_sync(self, prompt: str) -> str:
        if not self.gemini_key:
            raise ValueError("GEMINI_API_KEY not set")
        url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
               f"{self.gemini_model}:generateContent?key={self.gemini_key}")
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json"},
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=45) as r:
            data = json.loads(r.read())
            return data["candidates"][0]["content"]["parts"][0]["text"]

    async def _call_llm(self, prompt: str) -> str:
        loop = asyncio.get_event_loop()
        if self.groq_key:
            try:
                return await loop.run_in_executor(None, self._call_groq_sync, prompt)
            except Exception as e:
                print(f"[LLM] Groq failed: {e} — trying Gemini")
        if self.gemini_key:
            try:
                return await loop.run_in_executor(None, self._call_gemini_sync, prompt)
            except Exception as e:
                print(f"[LLM] Gemini failed: {e} — using mock")
        raise RuntimeError("All LLM providers failed")

    # ── Public API ────────────────────────────────────────────────────────────

    async def label_element(self, element_data: Dict[str, Any]) -> Dict[str, Any]:
        prompt = ELEMENT_LABEL_PROMPT.format(**{
            "tag":          element_data.get("tag", "input"),
            "input_type":   element_data.get("input_type", "text"),
            "element_id":   element_data.get("element_id", ""),
            "name":         element_data.get("name", ""),
            "placeholder":  element_data.get("placeholder", ""),
            "aria_label":   element_data.get("aria_label", ""),
            "label_text":   element_data.get("label_text", ""),
            "context":      element_data.get("context", "")[:200],
        })
        try:
            raw = await self._call_llm(prompt)
            return _extract_json(raw)
        except Exception as e:
            print(f"[LLM] label_element fallback: {e}")
            return self._mock_label(element_data)

    async def generate_test_cases(
        self,
        flow_name: str,
        start_url: str,
        steps: List[Dict],
        elements: List[Dict],
        expected_outcome: str,
        instructions: str = None,
    ) -> Dict[str, Any]:
        custom_block = ""
        if instructions and instructions.strip():
            custom_block = f"\n## Additional Instructions from User\n{instructions.strip()}\n"

        prompt = TEST_GENERATION_PROMPT.format(
            flow_name=flow_name,
            start_url=start_url,
            flow_steps_json=json.dumps(steps, indent=2),
            elements_json=json.dumps(elements, indent=2),
            expected_outcome=expected_outcome,
            custom_instructions_block=custom_block,
        )
        try:
            raw = await self._call_llm(prompt)
            result = _extract_json(raw)
            # Normalise key name typo that sometimes slips through
            if "test_cie_ases" in result:
                result["test_cases"] = result.pop("test_cie_ases")
            if "test_cases" not in result:
                raise ValueError("No test_cases key in LLM response")
            return result
        except Exception as e:
            print(f"[LLM] generate_test_cases fallback: {e}")
            return self._mock_test_cases(flow_name, start_url, steps, elements)

    # ── Deterministic offline fallback ────────────────────────────────────────

    def _mock_label(self, el: Dict) -> Dict:
        name = el.get("name") or el.get("placeholder") or el.get("element_id") or "field"
        return {
            "semantic_label": f"Form field: {name}",
            "field_type": "text",
            "purpose": f"Input field for {name}",
            "required": True,
            "max_length": None,
            "validation_rules": [{"rule": "required", "error_message": "This field is required"}],
            "stable_locator": f"[name='{name}']",
        }

    def _mock_test_cases(self, flow_name, start_url, steps, elements) -> Dict:
        """
        Offline fallback: generate a minimal but meaningful test suite
        from the recorded steps and detected elements without any LLM call.
        """
        from .test_data_service import test_data_service

        # Build fill-steps for each detected input element
        input_els = [e for e in elements
                     if e.get("tag") in ("input", "textarea", "select")
                     and e.get("input_type") not in ("submit", "button", "hidden", "reset")]

        def _selector(el):
            if el.get("element_id"):   return f"#{el['element_id']}"
            if el.get("name"):         return f"[name='{el['name']}']"
            if el.get("placeholder"):  return f"[placeholder='{el['placeholder']}']"
            return el.get("tag", "input")

        def _fill_steps(values_map):
            s = []
            for el in input_els:
                eid = el.get("element_id") or el.get("name") or el.get("placeholder") or "field"
                ftype = (el.get("input_type") or el.get("name") or "").lower()
                val = values_map.get(eid, test_data_service.get_values_for_field_type(ftype)[0][0])
                s.append({"element_id": eid, "action": "fill", "value": val})
            # Add recorded click/submit steps
            for step in steps:
                if step.get("action") == "click":
                    s.append({"element_id": step.get("selector", "submit"), "action": "click", "value": None})
            return s

        # Gather one valid value per field
        valid_map = {}
        for el in input_els:
            eid   = el.get("element_id") or el.get("name") or el.get("placeholder") or "field"
            ftype = (el.get("input_type") or el.get("name") or "").lower()
            vals  = test_data_service.get_values_for_field_type(ftype)
            valid_vals = [v for v, l in vals if l.startswith("valid")]
            valid_map[eid] = (valid_vals[0] if valid_vals else vals[0][0])

        test_cases = []

        # 1. Happy path
        test_cases.append({
            "name": f"{flow_name} — Happy Path",
            "category": "happy_path",
            "description": "Reproduce the recorded flow with valid data",
            "steps": _fill_steps(valid_map),
            "assertions": [
                {"type": "no_error_message", "expected": ""},
                {"type": "url_not_contains",  "expected": "error"},
            ],
            "confidence": 0.88,
        })

        # 2. Empty all required fields
        test_cases.append({
            "name": f"{flow_name} — All Fields Empty",
            "category": "negative",
            "description": "Submit without filling any fields; expect validation errors",
            "steps": [{"element_id": e.get("element_id") or e.get("name") or "field",
                        "action": "fill", "value": ""}
                       for e in input_els]
                    + [{"element_id": "submit", "action": "click", "value": None}],
            "assertions": [
                {"type": "error_message_present", "expected": "required"},
                {"type": "url_not_contains",       "expected": "/success"},
            ],
            "confidence": 0.90,
        })

        # 3. SQL injection in every field
        test_cases.append({
            "name": f"{flow_name} — SQL Injection",
            "category": "security",
            "description": "Inject SQL into every text field",
            "steps": _fill_steps({eid: "' OR '1'='1" for eid in valid_map}),
            "assertions": [
                {"type": "url_not_contains",    "expected": "/success"},
                {"type": "no_sql_error",         "expected": "syntax error"},
                {"type": "no_server_error",      "expected": "500"},
            ],
            "confidence": 0.92,
        })

        # 4. XSS in every field
        test_cases.append({
            "name": f"{flow_name} — XSS Payload",
            "category": "security",
            "description": "Inject script tags into every text field",
            "steps": _fill_steps({eid: "<script>alert('XSS')</script>" for eid in valid_map}),
            "assertions": [
                {"type": "no_alert_triggered",  "expected": ""},
                {"type": "url_not_contains",    "expected": "/success"},
            ],
            "confidence": 0.90,
        })

        # 5. Boundary — very long values
        test_cases.append({
            "name": f"{flow_name} — Max Length Boundary",
            "category": "edge_case",
            "description": "Fill every field with 300+ character string",
            "steps": _fill_steps({eid: "A" * 300 for eid in valid_map}),
            "assertions": [
                {"type": "no_server_error", "expected": "500"},
            ],
            "confidence": 0.85,
        })

        # 6. Unicode / international
        test_cases.append({
            "name": f"{flow_name} — Unicode Characters",
            "category": "edge_case",
            "description": "Fill fields with unicode, emoji, and RTL text",
            "steps": _fill_steps({eid: "日本語テスト 🎉 العربية" for eid in valid_map}),
            "assertions": [
                {"type": "no_server_error", "expected": "500"},
            ],
            "confidence": 0.83,
        })

        # 7. Per-field type-specific negative tests
        for el in input_els[:3]:  # top 3 inputs only to keep list manageable
            eid   = el.get("element_id") or el.get("name") or el.get("placeholder") or "field"
            ftype = (el.get("input_type") or el.get("name") or "").lower()
            vals  = test_data_service.get_values_for_field_type(ftype)
            invalid_vals = [(v, l) for v, l in vals if "invalid" in l or "boundary" in l]

            for inv_val, inv_label in invalid_vals[:2]:
                m = dict(valid_map)
                m[eid] = inv_val
                test_cases.append({
                    "name": f"{eid}: {inv_label.replace('_', ' ')}",
                    "category": "negative",
                    "description": f"Test {eid} with {inv_label} value: '{inv_val[:50]}'",
                    "steps": _fill_steps(m),
                    "assertions": [
                        {"type": "error_message_present", "expected": ""},
                        {"type": "url_not_contains",       "expected": "/success"},
                    ],
                    "confidence": 0.80,
                })

        return {"test_cases": test_cases}


llm_service = LLMService()
