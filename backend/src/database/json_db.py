import os
import json
import threading
from datetime import datetime
from typing import List, Dict, Any, Optional

DB_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "workflows_db.json"))

class JSONDatabase:
    _lock = threading.Lock()

    def __init__(self):
        self._init_db()

    def _init_db(self):
        with self._lock:
            if not os.path.exists(DB_FILE):
                self._write_raw({
                    "workflows": [],
                    "workflow_steps": [],
                    "pages": [],
                    "elements": []
                })

    def _read_raw(self) -> Dict[str, Any]:
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {
                "workflows": [],
                "workflow_steps": [],
                "pages": [],
                "elements": []
            }

    def _write_raw(self, data: Dict[str, Any]):
        with open(DB_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    # --- Workflows ---
    def create_workflow(self, name: str, url: str) -> Dict[str, Any]:
        with self._lock:
            data = self._read_raw()
            next_id = max([w["id"] for w in data["workflows"]] + [0]) + 1
            workflow = {
                "id": next_id,
                "name": name,
                "url": url,
                "created_at": datetime.utcnow().isoformat()
            }
            data["workflows"].append(workflow)
            self._write_raw(data)
            return workflow

    def get_workflow(self, workflow_id: int) -> Optional[Dict[str, Any]]:
        with self._lock:
            data = self._read_raw()
            for w in data["workflows"]:
                if w["id"] == workflow_id:
                    # Hydrate steps and their elements
                    steps = [s for s in data["workflow_steps"] if s["workflow_id"] == workflow_id]
                    steps = sorted(steps, key=lambda x: x["step_order"])
                    
                    hydrated_steps = []
                    for s in steps:
                        el = None
                        if s.get("element_id") is not None:
                            el = next((e for e in data["elements"] if e["id"] == s["element_id"]), None)
                        
                        hydrated_steps.append({
                            **s,
                            "element": el
                        })
                    
                    return {
                        **w,
                        "steps": hydrated_steps
                    }
            return None

    def get_workflows(self) -> List[Dict[str, Any]]:
        with self._lock:
            data = self._read_raw()
            # Sort workflows by created_at descending
            return sorted(data["workflows"], key=lambda x: x.get("created_at", ""), reverse=True)

    def delete_workflow(self, workflow_id: int) -> bool:
        with self._lock:
            data = self._read_raw()
            workflows = [w for w in data["workflows"] if w["id"] == workflow_id]
            if not workflows:
                return False
            
            data["workflows"] = [w for w in data["workflows"] if w["id"] != workflow_id]
            data["workflow_steps"] = [s for s in data["workflow_steps"] if s["workflow_id"] != workflow_id]
            self._write_raw(data)
            return True

    def clear_all(self):
        with self._lock:
            self._write_raw({
                "workflows": [],
                "workflow_steps": [],
                "pages": [],
                "elements": []
            })

    # --- Pages ---
    def get_or_create_page(self, url: str) -> Dict[str, Any]:
        with self._lock:
            data = self._read_raw()
            truncated_url = url[:768]
            page = next((p for p in data["pages"] if p["url"] == truncated_url), None)
            if not page:
                next_id = max([p["id"] for p in data["pages"]] + [0]) + 1
                page = {
                    "id": next_id,
                    "url": truncated_url,
                    "title": ""
                }
                data["pages"].append(page)
                self._write_raw(data)
            return page

    # --- Elements ---
    def create_element(self, page_id: int, element_type: str, text: Optional[str], selector: Optional[str], attributes: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            data = self._read_raw()
            next_id = max([e["id"] for e in data["elements"]] + [0]) + 1
            element = {
                "id": next_id,
                "page_id": page_id,
                "element_type": element_type,
                "text": text,
                "selector": selector,
                "attributes": json.dumps(attributes)
            }
            data["elements"].append(element)
            self._write_raw(data)
            return element

    # --- Workflow Steps ---
    def add_workflow_step(self, workflow_id: int, element_id: Optional[int], action: str, value: Optional[str], selector: Optional[str], url: str) -> Dict[str, Any]:
        with self._lock:
            data = self._read_raw()
            # Verify workflow exists
            if not any(w["id"] == workflow_id for w in data["workflows"]):
                raise ValueError(f"Workflow with id {workflow_id} not found")

            # Determine next step order
            steps = [s for s in data["workflow_steps"] if s["workflow_id"] == workflow_id]
            next_order = max([s["step_order"] for s in steps] + [0]) + 1

            next_id = max([s["id"] for s in data["workflow_steps"]] + [0]) + 1
            step = {
                "id": next_id,
                "workflow_id": workflow_id,
                "element_id": element_id,
                "step_order": next_order,
                "action": action,
                "value": value,
                "selector": selector,
                "url": url
            }
            data["workflow_steps"].append(step)
            self._write_raw(data)
            return step

    def count_workflow_steps(self, workflow_id: int) -> int:
        with self._lock:
            data = self._read_raw()
            return len([s for s in data["workflow_steps"] if s["workflow_id"] == workflow_id])

    def save_test_cases(self, workflow_id: int, test_cases: List[Dict[str, Any]]) -> bool:
        with self._lock:
            data = self._read_raw()
            for w in data["workflows"]:
                if w["id"] == workflow_id:
                    w["test_cases"] = test_cases
                    self._write_raw(data)
                    return True
            return False

json_db = JSONDatabase()
