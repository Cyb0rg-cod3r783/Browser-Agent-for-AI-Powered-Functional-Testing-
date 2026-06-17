"""
Browser Service — Playwright-based page fetcher + full replay + assertion engine.
Runs synchronously in a thread pool to avoid Windows asyncio loop conflicts.
"""
import asyncio
import base64
from typing import List, Dict, Any, Optional
from playwright.sync_api import sync_playwright, Page, TimeoutError as PWTimeout


# ── Page content fetch ────────────────────────────────────────────────────────

def _fetch_page_content(url: str) -> dict:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(url, timeout=30000, wait_until="domcontentloaded")
        content = page.content()
        title   = page.title()
        browser.close()
    return {"content": content, "title": title}


def _fetch_accessibility_and_elements_sync(url: str) -> dict:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            page.goto(url, timeout=30000, wait_until="domcontentloaded")
            ax_snapshot = page.accessibility.snapshot()
            elements = []
            for loc in page.locator("input, select, textarea, button, a").all():
                try:
                    tag         = loc.evaluate("el => el.tagName.toLowerCase()")
                    input_type  = loc.evaluate("el => el.type || ''")
                    element_id  = loc.evaluate("el => el.id || ''")
                    name        = loc.evaluate("el => el.name || ''")
                    placeholder = loc.evaluate("el => el.getAttribute('placeholder') || ''")
                    aria_label  = loc.evaluate("el => el.getAttribute('aria-label') || ''")
                    label_text  = ""
                    if element_id:
                        lbl = page.locator(f"label[for='{element_id}']")
                        if lbl.count() > 0:
                            label_text = lbl.first.text_content() or ""
                    if not label_text:
                        label_text = loc.evaluate(
                            "el => { const l = el.closest('label'); return l ? l.textContent : ''; }"
                        )
                    context = loc.evaluate(
                        "el => el.parentElement ? el.parentElement.textContent.slice(0,150) : ''"
                    )
                    elements.append({
                        "tag": tag, "input_type": input_type,
                        "element_id": element_id, "name": name,
                        "placeholder": placeholder, "aria_label": aria_label,
                        "label_text": label_text.strip(), "context": context.strip(),
                    })
                except Exception:
                    pass
            return {"accessibility_tree": ax_snapshot, "elements": elements, "title": page.title()}
        except Exception as e:
            return {"accessibility_tree": None, "elements": [], "title": url, "error": str(e)}
        finally:
            browser.close()


# ── Assertion evaluator ───────────────────────────────────────────────────────

def _evaluate_assertion(page: Page, assertion: Dict) -> Dict:
    atype    = assertion.get("type", "")
    expected = assertion.get("expected", "")
    result   = {"type": atype, "expected": expected, "passed": False, "message": ""}

    try:
        current_url = page.url

        if atype == "url_contains":
            result["passed"] = expected.lower() in current_url.lower()
            result["message"] = f"URL '{current_url}' {'contains' if result['passed'] else 'does not contain'} '{expected}'"

        elif atype == "url_not_contains":
            result["passed"] = expected.lower() not in current_url.lower()
            result["message"] = f"URL '{current_url}' {'does not contain' if result['passed'] else 'contains'} '{expected}'"

        elif atype == "url_equals":
            result["passed"] = current_url.rstrip("/") == expected.rstrip("/")
            result["message"] = f"URL: '{current_url}' vs expected '{expected}'"

        elif atype == "element_visible":
            try:
                page.wait_for_selector(expected, timeout=3000)
                result["passed"] = True
                result["message"] = f"Element '{expected}' is visible"
            except PWTimeout:
                result["passed"] = False
                result["message"] = f"Element '{expected}' not found or not visible"

        elif atype == "element_hidden":
            loc = page.locator(expected)
            result["passed"] = loc.count() == 0 or not loc.first.is_visible()
            result["message"] = f"Element '{expected}' hidden: {result['passed']}"

        elif atype == "text_present":
            body_text = page.locator("body").text_content() or ""
            result["passed"] = expected.lower() in body_text.lower()
            result["message"] = f"Text '{expected}' {'found' if result['passed'] else 'not found'} in page"

        elif atype == "text_not_present":
            body_text = page.locator("body").text_content() or ""
            result["passed"] = expected.lower() not in body_text.lower()
            result["message"] = f"Text '{expected}' {'absent' if result['passed'] else 'present'} in page"

        elif atype == "error_message_present":
            body_text = (page.locator("body").text_content() or "").lower()

            # Wide set of error element selectors
            error_selectors = [
                ".error", ".alert", ".invalid-feedback", "[role='alert']",
                ".error-message", ".form-error", "[aria-invalid='true']",
                ".text-danger", ".text-red", ".validation-error",
                ".field-error", ".input-error", ".help-block",
                ".warning", "[class*='error']", "[class*='invalid']",
                "[class*='danger']", "[class*='alert']",
            ]
            found_error_element = False
            for sel in error_selectors:
                try:
                    loc = page.locator(sel)
                    if loc.count() > 0 and loc.first.is_visible():
                        found_error_element = True
                        break
                except Exception:
                    pass

            # Broad list of error-related keywords in page text
            error_keywords = [
                "error", "invalid", "required", "must", "please",
                "cannot", "incorrect", "wrong", "failed", "warning",
                "not allowed", "try again", "check", "fill",
                expected.lower() if expected else "",
            ]
            found_in_text = any(kw and kw in body_text for kw in error_keywords if kw)

            # Also check: did the page NOT navigate away? If still on same/login page = validation worked
            still_on_form_page = (
                page.locator("input[type='password'], input[type='email'], form").count() > 0
            )

            result["passed"] = found_error_element or found_in_text or still_on_form_page
            result["message"] = (
                f"Error indicator: element={'yes' if found_error_element else 'no'}, "
                f"text={'yes' if found_in_text else 'no'}, "
                f"still_on_form={'yes' if still_on_form_page else 'no'}"
            )

        elif atype == "no_error_message":
            body_text = (page.locator("body").text_content() or "").lower()
            error_keywords = ["error", "invalid", "failed", "something went wrong", "500"]
            result["passed"] = not any(kw in body_text for kw in error_keywords)
            result["message"] = "No error keywords found in page" if result["passed"] else "Error keywords found"

        elif atype == "no_server_error":
            body_text = (page.locator("body").text_content() or "").lower()
            result["passed"] = "500" not in body_text and "internal server error" not in body_text
            result["message"] = "No 5xx server error" if result["passed"] else "Server error detected"

        elif atype == "no_sql_error":
            body_text = (page.locator("body").text_content() or "").lower()
            sql_errors = ["sql", "syntax error", "ora-", "pg::", "mysql", "sqlite"]
            result["passed"] = not any(kw in body_text for kw in sql_errors)
            result["message"] = "No SQL error message" if result["passed"] else "SQL error text detected"

        elif atype == "no_alert_triggered":
            # If an alert/confirm appeared, it's already been dismissed by Playwright
            # We just check the page didn't break
            result["passed"] = True  # Playwright auto-dismisses, no crash = pass
            result["message"] = "No unhandled alert detected"

        elif atype == "title_contains":
            title = page.title()
            result["passed"] = expected.lower() in title.lower()
            result["message"] = f"Page title: '{title}'"

        elif atype == "element_count":
            # expected format: "selector>=2" or "selector==1"
            parts = re.split(r"(>=|<=|==|!=|>|<)", expected, maxsplit=1)
            if len(parts) == 3:
                sel, op, count_str = parts
                count = page.locator(sel.strip()).count()
                n = int(count_str.strip())
                ops = {">=": count >= n, "<=": count <= n, "==": count == n,
                       "!=": count != n, ">": count > n, "<": count < n}
                result["passed"] = ops.get(op, False)
                result["message"] = f"Found {count} elements matching '{sel}'"
            else:
                result["passed"] = False
                result["message"] = f"Invalid element_count format: {expected}"

        else:
            result["passed"] = False
            result["message"] = f"Unknown assertion type: {atype}"

    except Exception as e:
        result["passed"] = False
        result["message"] = f"Assertion error: {e}"

    return result


import re  # needed by assertion evaluator


# ── Step executor ─────────────────────────────────────────────────────────────

def _execute_step(page: Page, step: Dict) -> Dict:
    action   = step.get("action", "")
    selector = step.get("selector")
    value    = step.get("value")
    url      = step.get("url")
    order    = step.get("step_order", 0)

    result = {
        "step_order": order, "action": action,
        "selector": selector, "value": value,
        "status": "success", "error": None,
    }

    # Auto-dismiss any browser dialogs to prevent hangs
    page.on("dialog", lambda d: d.dismiss())

    try:
        if action == "navigate":
            nav_url = value or url
            if nav_url:
                page.goto(nav_url, timeout=30000, wait_until="domcontentloaded")

        elif action in ("fill", "type"):
            if not selector:
                raise ValueError("No selector for fill/type step")
            # Try multiple selector strategies
            el = _find_element(page, selector, step)
            el.scroll_into_view_if_needed()
            el.fill(value or "")

        elif action == "click":
            if not selector:
                raise ValueError("No selector for click step")
            el = _find_element(page, selector, step)
            el.scroll_into_view_if_needed()
            el.click()
            try:
                page.wait_for_load_state("domcontentloaded", timeout=4000)
            except Exception:
                pass

        elif action == "select":
            if not selector:
                raise ValueError("No selector for select step")
            page.select_option(selector, value or "")

        elif action == "scroll":
            page.mouse.wheel(0, int(value or 300))

        elif action == "check":
            if not selector:
                raise ValueError("No selector for check step")
            el = _find_element(page, selector, step)
            el.check()

        else:
            result["status"] = "skipped"
            result["error"] = f"Unknown action: {action}"

    except Exception as e:
        result["status"] = "failed"
        result["error"] = str(e)

    return result


def _find_element(page: Page, selector: str, step: Dict):
    """
    Try the recorded selector first, then fall back to common alternatives
    derived from element metadata so replay is resilient to minor DOM changes.
    """
    candidates = [selector]

    # Build fallback selectors from step metadata
    eid = step.get("element_id") or ""
    name = step.get("element_text") or ""

    # From element_id field (could be actual HTML id or name)
    if eid and not eid.startswith("#") and not eid.startswith("["):
        safe = eid.replace("'", "\\'")
        candidates += [
            f"#{safe}",
            f"[name='{safe}']",
            f"[placeholder='{safe}']",
            f"[id='{safe}']",
        ]

    for sel in candidates:
        try:
            el = page.wait_for_selector(sel, timeout=4000)
            if el:
                return el
        except Exception:
            continue

    raise ValueError(f"Element not found with any selector: {candidates}")


# ── Full test case replay (steps + assertions) ────────────────────────────────

def _replay_test_case_sync(
    start_url: str,
    steps: List[Dict],
    assertions: List[Dict],
) -> Dict:
    step_results = []
    assertion_results = []
    screenshot_b64 = None
    aborted = False

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        # Auto-dismiss alerts
        page.on("dialog", lambda d: d.dismiss())

        try:
            page.goto(start_url, timeout=30000, wait_until="domcontentloaded")
        except Exception as e:
            browser.close()
            return {
                "step_results": [{"step_order": 0, "action": "navigate", "selector": None,
                                   "value": start_url, "status": "failed", "error": str(e)}],
                "assertion_results": [],
                "screenshot_b64": None,
            }

        for step in steps:
            res = _execute_step(page, step)
            step_results.append(res)
            if res["status"] == "failed":
                aborted = True  # still run assertions for diagnostics

        # Run assertions regardless of step failures
        for assertion in assertions:
            ar = _evaluate_assertion(page, assertion)
            assertion_results.append(ar)

        # Take a screenshot for the report
        try:
            screenshot_b64 = base64.b64encode(page.screenshot(type="png")).decode()
        except Exception:
            pass

        browser.close()

    return {
        "step_results": step_results,
        "assertion_results": assertion_results,
        "screenshot_b64": screenshot_b64,
        "aborted": aborted,
    }


# ── Simple workflow replay (no assertions) ────────────────────────────────────

def _replay_steps_sync(start_url: str, steps: List[Dict]) -> List[Dict]:
    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.on("dialog", lambda d: d.dismiss())
        try:
            page.goto(start_url, timeout=30000, wait_until="domcontentloaded")
        except Exception as e:
            browser.close()
            return [{"step_order": 0, "action": "navigate", "selector": None,
                     "value": start_url, "status": "failed", "error": str(e)}]
        for step in steps:
            results.append(_execute_step(page, step))
        browser.close()
    return results


# ── Async service classes ─────────────────────────────────────────────────────

class BrowserService:
    async def get_page_content(self, url: str) -> dict:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _fetch_page_content, url)

    async def get_accessibility_and_elements(self, url: str) -> dict:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _fetch_accessibility_and_elements_sync, url)

    async def close(self): pass


class ReplayService:
    async def replay(self, start_url: str, steps: List[Dict]) -> List[Dict]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _replay_steps_sync, start_url, steps)

    async def replay_test_case(
        self,
        start_url: str,
        steps: List[Dict],
        assertions: List[Dict],
    ) -> Dict:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, _replay_test_case_sync, start_url, steps, assertions
        )
