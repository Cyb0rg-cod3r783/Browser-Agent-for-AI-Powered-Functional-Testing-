"""
LLM Service — AI-powered test case generator.
Uses Groq (primary) → Gemini (fallback) → deterministic mock (offline fallback).

Strategy: split generation into 4 focused LLM calls (one per category) so each
call stays within the 8k token output limit of llama-3.1-8b-instant, then merge.
Total target: 50+ test cases.
"""
import json
import re
import urllib.request
import urllib.error
import asyncio
from typing import Dict, Any, List
from ..core.config import settings

# ── Per-category prompts ──────────────────────────────────────────────────────

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

# Shared context block — built as a plain string, NOT via .format()
def _build_context(flow_name, start_url, flow_steps_json, elements_json, custom_block):
    return f"""
## Workflow
Flow: {flow_name}
URL: {start_url}

## What the user recorded (IMPORTANT — use these to understand field types)
The "recorded_value" in each element is what the user ACTUALLY TYPED during recording.
Use it to infer the true field type and generate realistic test variations.
For example:
- If recorded_value is "soham@example.com" → this is an EMAIL field → generate email test cases
- If recorded_value is "Pass@1234" → this is a PASSWORD field → generate password test cases
- If recorded_value is "9876543210" → this is a PHONE/NUMBER field → generate number test cases
- If recorded_value is "John Doe" → this is a NAME field → generate name test cases

Recorded steps: {flow_steps_json}
Detected elements (with recorded values): {elements_json}
{custom_block}
"""

HAPPY_PATH_TEMPLATE = """
{context}

## Task — HAPPY PATH tests (generate exactly 3)
Generate 3 happy_path test cases:
1. Exact reproduction of the recorded steps with the same valid values
2. Alternative valid data (different but still valid inputs for every field)
3. Minimal valid input (shortest/simplest values that still pass validation)

Rules:
- Use REAL concrete values, not placeholders
- Each test must have at least 2 assertions
- Assertions: url_contains, element_visible, no_error_message, title_contains

Respond ONLY with valid JSON:
{{"test_cases": [
  {{"name":"...", "category":"happy_path", "description":"...",
    "steps":[{{"element_id":"...","action":"fill","value":"..."}}],
    "assertions":[{{"type":"...","expected":"..."}}],
    "confidence":0.95}}
]}}
"""

NEGATIVE_TEMPLATE = """
{context}

## Task — NEGATIVE tests (generate exactly 20)
Generate 20 negative test cases covering ALL of:

1. Empty required fields (one per field, one test each)
2. Wrong data type per field:
   - Email field: plain text, number, special chars only
   - Password field: too short (1 char), no uppercase, no number, no special char
   - Name field: numbers only, special chars only
   - Phone/number field: letters, negative number, decimal where integer expected
3. Invalid format per field:
   - Email: missing @, missing domain, double @, spaces inside
   - Password: only spaces, only repeated char
4. Boundary violations:
   - Too long (300 chars, 1000 chars, 5000 chars)
   - Exactly 1 character
   - Only whitespace

Use REAL concrete values for every step. Include at least 2 assertions per test.
Assertions to use: error_message_present, url_not_contains, text_present, no_server_error

Respond ONLY with valid JSON:
{{"test_cases": [
  {{"name":"...", "category":"negative", "description":"...",
    "steps":[{{"element_id":"...","action":"fill","value":"..."}}],
    "assertions":[{{"type":"...","expected":"..."}}],
    "confidence":0.90}}
]}}
"""

EDGE_CASE_TEMPLATE = """
{context}

## Task — EDGE CASE tests (generate exactly 15)
Generate 15 edge_case test cases covering ALL of:

1. Unicode and internationalisation:
   - Japanese: Tanaka Taro, test input
   - Arabic (RTL): hello world in Arabic
   - Chinese: test username
   - Emoji: test fire emoji user
   - Mixed scripts: Unicode Test 123
2. Whitespace edge cases:
   - Leading spaces only
   - Trailing spaces only
   - Only spaces (5, 10, 50)
   - Tab characters, newlines embedded
3. Special characters: !@#$%^&*()_+-=[]
4. Number boundaries: 0, -1, 2147483647, 2147483648
5. Repeated / pattern values:
   - All same char: aaaaaaa, 1111111
   - Alternating: ababababab
   - Very short valid: single char

Respond ONLY with valid JSON:
{{"test_cases": [
  {{"name":"...", "category":"edge_case", "description":"...",
    "steps":[{{"element_id":"...","action":"fill","value":"..."}}],
    "assertions":[{{"type":"...","expected":"..."}}],
    "confidence":0.85}}
]}}
"""

SECURITY_TEMPLATE = """
{context}

## Task — SECURITY tests (generate exactly 12)
Generate 12 security test cases covering ALL of:

1. SQL Injection (4 tests):
   - Classic: ' OR '1'='1
   - Drop table: '; DROP TABLE users; --
   - Union: ' UNION SELECT username,password FROM users--
   - Blind: '; WAITFOR DELAY '0:0:5'--

2. XSS Cross-Site Scripting (4 tests):
   - Script tag: <script>alert('XSS')</script>
   - Image onerror: <img src=x onerror=alert(1)>
   - SVG: <svg onload=alert(1)>
   - Event handler attribute injection

3. Other injections (4 tests):
   - Command injection: ; ls -la
   - Path traversal: ../../../etc/passwd
   - LDAP injection: *)(uid=*))(|(uid=*
   - Server-side template injection: template expression payloads

For every security test assert: no_server_error, no_sql_error, no_alert_triggered, url_not_contains /success

Respond ONLY with valid JSON:
{{"test_cases": [
  {{"name":"...", "category":"security", "description":"...",
    "steps":[{{"element_id":"...","action":"fill","value":"..."}}],
    "assertions":[{{"type":"...","expected":"..."}}],
    "confidence":0.93}}
]}}
"""


# ── JSON extractor ────────────────────────────────────────────────────────────

def _extract_json(text: str) -> dict:
    text = re.sub(r"```(?:json)?", "", text).strip()
    start = text.find("{")
    end   = text.rfind("}") + 1
    if start == -1 or end == 0:
        raise ValueError(f"No JSON object found: {text[:300]}")
    return json.loads(text[start:end])


# ── LLMService ────────────────────────────────────────────────────────────────

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
        payload = {
            "model": self.groq_model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2,
            "max_tokens": 8000,
            "response_format": {"type": "json_object"},
        }
        req = urllib.request.Request(
            "https://api.groq.com/openai/v1/chat/completions",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {self.groq_key}"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as r:
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
        with urllib.request.urlopen(req, timeout=60) as r:
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
                print(f"[LLM] Gemini failed: {e}")
        raise RuntimeError("All LLM providers failed")

    # ── Element labeller ──────────────────────────────────────────────────────

    async def label_element(self, element_data: Dict[str, Any]) -> Dict[str, Any]:
        prompt = ELEMENT_LABEL_PROMPT.format(**{
            "tag":         element_data.get("tag", "input"),
            "input_type":  element_data.get("input_type", "text"),
            "element_id":  element_data.get("element_id", ""),
            "name":        element_data.get("name", ""),
            "placeholder": element_data.get("placeholder", ""),
            "aria_label":  element_data.get("aria_label", ""),
            "label_text":  element_data.get("label_text", ""),
            "context":     element_data.get("context", "")[:200],
        })
        try:
            raw = await self._call_llm(prompt)
            return _extract_json(raw)
        except Exception as e:
            print(f"[LLM] label_element fallback: {e}")
            return self._mock_label(element_data)

    # ── Main generator: 4 parallel LLM calls, one per category ───────────────

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
            custom_block = f"## Additional Instructions\n{instructions.strip()}"

        ctx = dict(
            flow_name=flow_name,
            start_url=start_url,
            flow_steps_json=json.dumps(steps, indent=2),
            elements_json=json.dumps(elements, indent=2),
            custom_block=custom_block,
        )

        context_str = _build_context(**ctx)

        prompts = {
            "happy":    HAPPY_PATH_TEMPLATE.format(context=context_str),
            "negative": NEGATIVE_TEMPLATE.format(context=context_str),
            "edge":     EDGE_CASE_TEMPLATE.format(context=context_str),
            "security": SECURITY_TEMPLATE.format(context=context_str),
        }

        # Fire all 4 calls concurrently
        results = await asyncio.gather(
            *[self._call_category(name, prompt)
              for name, prompt in prompts.items()],
            return_exceptions=True
        )

        all_cases: List[Dict] = []
        for name, result in zip(prompts.keys(), results):
            if isinstance(result, Exception):
                print(f"[LLM] {name} category failed: {result} — using mock fallback for this category")
                all_cases.extend(self._mock_category(name, flow_name, start_url, steps, elements))
            else:
                all_cases.extend(result)

        print(f"[LLM] Total test cases generated: {len(all_cases)}")
        return {"test_cases": all_cases}

    async def _call_category(self, name: str, prompt: str) -> List[Dict]:
        """Call LLM for one category and return its test_cases list."""
        raw = await self._call_llm(prompt)
        result = _extract_json(raw)
        cases = result.get("test_cases", [])
        print(f"[LLM] {name}: {len(cases)} test cases")
        return cases

    # ── Mock label ────────────────────────────────────────────────────────────

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

    # ── Mock fallbacks per category (used when LLM call fails) ───────────────

    def _mock_category(self, category: str, flow_name: str, start_url: str,
                       steps: List[Dict], elements: List[Dict]) -> List[Dict]:
        from .test_data_service import test_data_service

        # Filter to actual input elements — support both raw and enriched element dicts
        input_els = [e for e in elements
                     if e.get("tag") in ("input", "textarea", "select")
                     and e.get("input_type") not in ("submit", "button", "hidden", "reset")]

        # If no input elements found from elements list, extract from recorded steps
        if not input_els:
            seen = set()
            for s in steps:
                if s.get("action") in ("fill", "type") and s.get("selector"):
                    sel = s["selector"]
                    if sel not in seen:
                        seen.add(sel)
                        input_els.append({
                            "tag": "input",
                            "input_type": "text",
                            "element_id": sel,
                            "name": sel,
                            "placeholder": "",
                            "stable_locator": sel,
                        })

        def eid(el):
            return (el.get("stable_locator") or el.get("element_id")
                    or el.get("name") or el.get("placeholder") or "field")

        def ftype(el):
            # Prefer inferred type from recorded value — most accurate signal
            return (el.get("recorded_value_type")
                    or el.get("input_type")
                    or el.get("field_type")
                    or el.get("name") or "").lower()

        def valid_for(el):
            """Return best valid value: recorded value first, then type-appropriate fallback."""
            if el.get("recorded_value"):
                return el["recorded_value"]
            vals = test_data_service.get_values_for_field_type(ftype(el))
            valid_vals = [v for v, l in vals if l.startswith("valid")]
            return valid_vals[0] if valid_vals else "testvalue123"

        # Find the real submit selector from recorded steps
        submit_selector = "submit"
        for s in steps:
            if s.get("action") == "click" and s.get("selector"):
                sel = s["selector"]
                # Prefer selectors that look like submit buttons
                if any(k in sel.lower() for k in ["submit", "btn", "button", "login", "sign"]):
                    submit_selector = sel
                    break
            # Also check element_id
            if s.get("action") == "click" and s.get("element_id"):
                eid_val = s["element_id"]
                if any(k in eid_val.lower() for k in ["submit", "btn", "button", "login", "sign"]):
                    submit_selector = eid_val
                    break

        def fill(values_map):
            s = []
            for el in input_els:
                e = eid(el)
                s.append({"element_id": e, "action": "fill",
                          "value": values_map.get(e, "testvalue")})
            s.append({"element_id": submit_selector, "action": "click", "value": None})
            return s

        valid_map = {}
        for el in input_els:
            e = eid(el)
            valid_map[e] = valid_for(el)

        cases = []

        if category == "happy":
            cases.append({"name": f"{flow_name} — Happy Path", "category": "happy_path",
                "description": "Reproduce recorded flow", "steps": fill(valid_map),
                "assertions": [{"type": "no_error_message", "expected": ""},
                                {"type": "url_not_contains", "expected": "error"}],
                "confidence": 0.88})
            cases.append({"name": f"{flow_name} — Alternative Valid Data", "category": "happy_path",
                "description": "Different valid values", "steps": fill({e: "AltUser123!" for e in valid_map}),
                "assertions": [{"type": "no_server_error", "expected": "500"}],
                "confidence": 0.82})
            cases.append({"name": f"{flow_name} — Minimal Valid Input", "category": "happy_path",
                "description": "Shortest valid input", "steps": fill({e: "a" for e in valid_map}),
                "assertions": [{"type": "no_server_error", "expected": "500"}],
                "confidence": 0.75})

        elif category == "negative":
            # 20 negative tests from test_data_service
        neg_tests = [
            ("All Empty",      {e: "" for e in valid_map},                                        "error_message_present", "required"),
            ("SQL Inject",     {e: "' OR '1'='1" for e in valid_map},                            "no_sql_error",          "syntax"),
            ("XSS Script",     {e: "<script>alert(1)</script>" for e in valid_map},              "no_alert_triggered",    ""),
            ("Long 300",       {e: "A" * 300 for e in valid_map},                                "no_server_error",       "500"),
            ("Long 1000",      {e: "B" * 1000 for e in valid_map},                               "no_server_error",       "500"),
            ("Spaces Only",    {e: "   " for e in valid_map},                                     "error_message_present", ""),
            ("Null Byte",      {e: "test\x00value" for e in valid_map},                          "no_server_error",       "500"),
            ("Newlines",       {e: "line1\nline2\nline3" for e in valid_map},                     "no_server_error",       "500"),
            ("Tabs",           {e: "val\t\t\t" for e in valid_map},                              "no_server_error",       "500"),
            ("All Numbers",    {e: "1234567890" for e in valid_map},                              "error_message_present", ""),
            ("All Specials",   {e: "!@#$%^&*()" for e in valid_map},                             "no_server_error",       "500"),
            ("Very Short 1",   {e: "a" for e in valid_map},                                       "no_server_error",       ""),
            ("Int Max+1",      {e: "2147483648" for e in valid_map},                              "no_server_error",       "500"),
            ("Negative Num",   {e: "-999999" for e in valid_map},                                 "no_server_error",       "500"),
            ("Float Value",    {e: "3.14159" for e in valid_map},                                 "no_server_error",       "500"),
            ("HTML Tags",      {e: "<b>bold</b><i>italic</i>" for e in valid_map},               "no_alert_triggered",    ""),
            ("Path Traversal", {e: "../../../etc/passwd" for e in valid_map},                     "no_server_error",       "500"),
            ("URL Encoded",    {e: "%3Cscript%3Ealert%281%29%3C/script%3E" for e in valid_map}, "no_alert_triggered",    ""),
            ("Unicode Null",   {e: "\u0000\u0001\u0002" for e in valid_map},                     "no_server_error",       "500"),
            ("Repeated Char",  {e: "aaaaaaaaaaaaaaaaaaaaa" for e in valid_map},                   "no_server_error",       "500"),
        ]

        # Add field-type-specific invalid values based on what was recorded
        for el in input_els[:3]:
            e     = eid(el)
            ft    = ftype(el)
            rv    = el.get("recorded_value")
            vals  = test_data_service.get_values_for_field_type(ft)
            inv   = [(v, l) for v, l in vals if "invalid" in l or "boundary" in l]
            for inv_val, inv_label in inv[:3]:
                m = dict(valid_map); m[e] = inv_val
                neg_tests.append((
                    f"{e}: {inv_label.replace('_',' ')}",
                    m, "error_message_present", ""
                ))
                if len(neg_tests) >= 25:
                    break
            for label, vmap, assert_type, assert_exp in neg_tests:
                cases.append({
                    "name": f"{flow_name} — {label}",
                    "category": "negative",
                    "description": f"Test with {label} input",
                    "steps": fill(vmap),
                    "assertions": [
                        {"type": assert_type, "expected": assert_exp},
                        {"type": "url_not_contains", "expected": "/success"},
                    ],
                    "confidence": 0.85,
                })

        elif category == "edge":
            edge_tests = [
                ("Japanese Text",      {e: "田中太郎テスト" for e in valid_map}),
                ("Arabic RTL",         {e: "مرحبا بالعالم" for e in valid_map}),
                ("Chinese",            {e: "测试用户名输入" for e in valid_map}),
                ("Emoji",              {e: "🎉🚀💥User🔥" for e in valid_map}),
                ("Mixed Scripts",      {e: "Ünïcödé Tëst" for e in valid_map}),
                ("Leading Space",      {e: "  leadingspace" for e in valid_map}),
                ("Trailing Space",     {e: "trailingspace  " for e in valid_map}),
                ("50 Spaces",          {e: " " * 50 for e in valid_map}),
                ("Zero Value",         {e: "0" for e in valid_map}),
                ("Negative One",       {e: "-1" for e in valid_map}),
                ("Max Int",            {e: "2147483647" for e in valid_map}),
                ("Float Precision",    {e: "1.123456789012" for e in valid_map}),
                ("All Same Char",      {e: "z" * 50 for e in valid_map}),
                ("Alternating Chars",  {e: "abababababababab" for e in valid_map}),
                ("URL in Field",       {e: "https://evil.com/hack" for e in valid_map}),
            ]
            for label, vmap in edge_tests:
                cases.append({
                    "name": f"{flow_name} — {label}",
                    "category": "edge_case",
                    "description": f"Edge case: {label}",
                    "steps": fill(vmap),
                    "assertions": [{"type": "no_server_error", "expected": "500"}],
                    "confidence": 0.80,
                })

        elif category == "security":
            sec_tests = [
                ("SQL Classic",       {e: "' OR '1'='1" for e in valid_map}),
                ("SQL Drop Table",    {e: "'; DROP TABLE users; --" for e in valid_map}),
                ("SQL Union",         {e: "' UNION SELECT 1,username,password FROM users--" for e in valid_map}),
                ("SQL Blind Time",    {e: "'; WAITFOR DELAY '0:0:5'--" for e in valid_map}),
                ("XSS Script Tag",    {e: "<script>alert('XSS')</script>" for e in valid_map}),
                ("XSS Img onerror",   {e: "<img src=x onerror=alert(1)>" for e in valid_map}),
                ("XSS SVG",           {e: "<svg onload=alert(1)>" for e in valid_map}),
                ("XSS Event",         {e: '" onmouseover="alert(1)' for e in valid_map}),
                ("Cmd Injection",     {e: "; ls -la | cat /etc/passwd" for e in valid_map}),
                ("Path Traversal",    {e: "../../../etc/passwd" for e in valid_map}),
                ("LDAP Injection",    {e: "*)(uid=*))(|(uid=*" for e in valid_map}),
                ("Template Inject",   {e: "{{7*7}}${7*7}#{7*7}" for e in valid_map}),
            ]
            for label, vmap in sec_tests:
                cases.append({
                    "name": f"{flow_name} — {label}",
                    "category": "security",
                    "description": f"Security test: {label}",
                    "steps": fill(vmap),
                    "assertions": [
                        {"type": "no_server_error",    "expected": "500"},
                        {"type": "no_sql_error",       "expected": "syntax"},
                        {"type": "no_alert_triggered", "expected": ""},
                        {"type": "url_not_contains",   "expected": "/success"},
                    ],
                    "confidence": 0.92,
                })

        return cases

    def _mock_test_cases(self, flow_name, start_url, steps, elements) -> Dict:
        """Full offline fallback — combines all 4 category mocks."""
        all_cases = []
        for cat in ("happy", "negative", "edge", "security"):
            all_cases.extend(
                self._mock_category(cat, flow_name, start_url, steps, elements)
            )
        print(f"[Mock] Generated {len(all_cases)} test cases offline")
        return {"test_cases": all_cases}


llm_service = LLMService()
