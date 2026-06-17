import json
import urllib.request
import urllib.error
import asyncio
from typing import Dict, Any, List
from ..core.config import settings

ELEMENT_LABEL_PROMPT = """
Analyze this web element and provide a semantic label.

Element data:
tag: {tag}
type: {input_type}
id: {element_id}
name: {name}
placeholder: {placeholder}
aria_label: {aria_label}
associated_label_text: {label_text}
surrounding_text_context: {context}

Respond ONLY with valid JSON, no preamble:
{{
  "semantic_label": "short descriptive label (3-8 words)",
  "purpose": "one sentence description of what this field does",
  "validation_rules": [
    {{"rule": "required"}},
    {{"rule": "email_format", "typical_error": "Please enter a valid email address"}}
  ],
  "stable_locator_ranking": ["aria_label", "placeholder", "id", "css"]
}}
"""

TEST_GENERATION_PROMPT = """
You are generating functional test cases for this observed user flow.

Flow name: {flow_name}
Start URL: {start_url}
Steps observed (happy path):
{flow_steps_json}

Form elements on this page:
{elements_json}

Observed success state: {expected_outcome}

Generate test cases as JSON. Include:
1. Exactly 1 happy_path test (reproduce what was observed)
2. 3-5 negative tests (invalid inputs, missing required fields, wrong formats)
3. 2-3 edge_case tests (boundary values, unusual but potentially valid inputs)

For each test case, include concrete step-by-step values and specific assertions.

Respond ONLY with valid JSON:
{{"test_cases": [
  {{
    "name": "Login Happy Path",
    "category": "happy_path",
    "steps": [{{"element_id": "...", "action": "fill", "value": "..."}}],
    "assertions": [{{"type": "url_contains", "expected": "/dashboard"}}],
    "confidence": 0.95
  }}
]}}
"""

class LLMService:
    def __init__(self):
        self.api_key = settings.GEMINI_API_KEY
        # Use gemini-1.5-flash as default stable model
        self.model = "gemini-1.5-flash"

    def _call_gemini_sync(self, prompt: str) -> str:
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY is not set.")

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"
        headers = {
            "Content-Type": "application/json"
        }
        payload = {
            "contents": [{
                "parts": [{"text": prompt}]
            }],
            "generationConfig": {
                "responseMimeType": "application/json"
            }
        }

        req = urllib.request.Request(
            url, 
            data=json.dumps(payload).encode("utf-8"), 
            headers=headers, 
            method="POST"
        )

        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                resp_data = json.loads(response.read().decode("utf-8"))
                candidates = resp_data.get("candidates", [])
                if not candidates:
                    raise ValueError(f"No response candidates from Gemini API: {resp_data}")
                
                text_content = candidates[0]["content"]["parts"][0]["text"]
                return text_content
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8")
            raise ValueError(f"Gemini API request failed with code {e.code}: {error_body}")
        except Exception as e:
            raise ValueError(f"Failed to communicate with Gemini API: {e}")

    async def call_gemini(self, prompt: str) -> str:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._call_gemini_sync, prompt)

    async def label_element(self, element_data: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze a web element and return semantic labeling and validation rules."""
        prompt = ELEMENT_LABEL_PROMPT.format(
            tag=element_data.get("tag", "input"),
            input_type=element_data.get("input_type", "text"),
            element_id=element_data.get("element_id", ""),
            name=element_data.get("name", ""),
            placeholder=element_data.get("placeholder", ""),
            aria_label=element_data.get("aria_label", ""),
            label_text=element_data.get("label_text", ""),
            context=element_data.get("context", "")
        )

        if not self.api_key:
            # Fallback mock labeling when API key is missing
            return self._mock_label_element(element_data)

        try:
            response_text = await self.call_gemini(prompt)
            return json.loads(response_text)
        except Exception as e:
            print(f"Error calling LLM for element labeling: {e}. Falling back to mock.")
            return self._mock_label_element(element_data)

    async def generate_test_cases(self, flow_name: str, start_url: str, steps: List[Dict[str, Any]], elements: List[Dict[str, Any]], expected_outcome: str) -> Dict[str, Any]:
        """Generate happy path, negative, and edge cases for the flow."""
        prompt = TEST_GENERATION_PROMPT.format(
            flow_name=flow_name,
            start_url=start_url,
            flow_steps_json=json.dumps(steps, indent=2),
            elements_json=json.dumps(elements, indent=2),
            expected_outcome=expected_outcome
        )

        if not self.api_key:
            # Fallback mock test generation when API key is missing
            return self._mock_test_cases(flow_name, start_url, steps)

        try:
            response_text = await self.call_gemini(prompt)
            result = json.loads(response_text)
            
            # Handle possible key misspelling in the prompt
            if "test_cie ases" in result:
                result["test_cases"] = result.pop("test_cie ases")
                
            return result
        except Exception as e:
            print(f"Error calling LLM for test generation: {e}. Falling back to mock.")
            return self._mock_test_cases(flow_name, start_url, steps)

    def _mock_label_element(self, el: Dict[str, Any]) -> Dict[str, Any]:
        name_or_placeholder = el.get("name") or el.get("placeholder") or el.get("element_id") or "field"
        label = f"Mock semantic label for {name_or_placeholder}"
        return {
            "semantic_label": label,
            "purpose": f"Allows user to input or select {name_or_placeholder}.",
            "validation_rules": [
                {"rule": "required" if el.get("required") else "optional"}
            ],
            "stable_locator_ranking": ["aria_label", "placeholder", "id", "css"]
        }

    def _mock_test_cases(self, flow_name: str, start_url: str, steps: List[Dict[str, Any]]) -> Dict[str, Any]:
        return {
            "test_cases": [
                {
                    "name": f"{flow_name} Happy Path",
                    "category": "happy_path",
                    "steps": [
                        {
                            "element_id": s.get("selector") or f"step-{idx}",
                            "action": s.get("action", "click"),
                            "value": s.get("value")
                        } for idx, s in enumerate(steps)
                    ],
                    "assertions": [
                        {
                            "type": "url_contains",
                            "expected": start_url
                        }
                    ],
                    "confidence": 0.85
                },
                {
                    "name": f"{flow_name} Empty Inputs Negative Path",
                    "category": "negative",
                    "steps": [],
                    "assertions": [
                        {
                            "type": "error_message_present",
                            "expected": "Required field"
                        }
                    ],
                    "confidence": 0.80
                }
            ]
        }

llm_service = LLMService()
