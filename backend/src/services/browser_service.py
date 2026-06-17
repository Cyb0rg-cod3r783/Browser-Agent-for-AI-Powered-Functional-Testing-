import asyncio
from typing import List, Dict, Any
from playwright.sync_api import sync_playwright


# ── Page content fetch (used by /record/start) ────────────────────────────────

def _fetch_page_content(url: str) -> dict:
    """Fetch raw HTML of a page synchronously (runs in a thread)."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(url, timeout=30000, wait_until="domcontentloaded")
        content = page.content()
        title = page.title()
        browser.close()
    return {"content": content, "title": title}


def _fetch_accessibility_and_elements_sync(url: str) -> dict:
    """Fetch accessibility snapshot and detailed form elements synchronously."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            page.goto(url, timeout=30000, wait_until="domcontentloaded")
            ax_snapshot = page.accessibility.snapshot()
            
            elements = []
            # Gather common form inputs and interactive elements
            locators = page.locator('input, select, textarea, button, a').all()
            for loc in locators:
                try:
                    tag = loc.evaluate("el => el.tagName.toLowerCase()")
                    # Skip anchor tags that have no text and no child elements, or keep them
                    input_type = loc.evaluate("el => el.type || ''")
                    element_id = loc.evaluate("el => el.id || ''")
                    name = loc.evaluate("el => el.name || ''")
                    placeholder = loc.evaluate("el => el.getAttribute('placeholder') || ''")
                    aria_label = loc.evaluate("el => el.getAttribute('aria-label') || ''")
                    
                    label_text = ""
                    if element_id:
                        lbl = page.locator(f"label[for='{element_id}']")
                        if lbl.count() > 0:
                            label_text = lbl.first.text_content() or ""
                    if not label_text:
                        label_text = loc.evaluate("el => { const lbl = el.closest('label'); return lbl ? lbl.textContent : ''; }")
                    
                    context = loc.evaluate("el => el.parentElement ? el.parentElement.textContent.slice(0, 150) : ''")
                    
                    elements.append({
                        "tag": tag,
                        "input_type": input_type,
                        "element_id": element_id,
                        "name": name,
                        "placeholder": placeholder,
                        "aria_label": aria_label,
                        "label_text": label_text.strip(),
                        "context": context.strip()
                    })
                except Exception as ex:
                    print(f"Skipping element info fetch: {ex}")
            
            return {
                "accessibility_tree": ax_snapshot,
                "elements": elements,
                "title": page.title()
            }
        except Exception as e:
            return {
                "accessibility_tree": None,
                "elements": [],
                "title": url,
                "error": str(e)
            }
        finally:
            browser.close()


class BrowserService:
    async def get_page_content(self, url: str) -> dict:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _fetch_page_content, url)

    async def get_accessibility_and_elements(self, url: str) -> dict:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _fetch_accessibility_and_elements_sync, url)

    async def close(self):
        pass


# ── Replay engine ─────────────────────────────────────────────────────────────

def _replay_steps_sync(start_url: str, steps: List[Dict[str, Any]]) -> List[Dict]:
    """
    Replay a list of recorded steps synchronously in a thread.
    Returns a list of per-step results.
    """
    results = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # Navigate to the starting URL
        try:
            page.goto(start_url, timeout=30000, wait_until="domcontentloaded")
        except Exception as e:
            browser.close()
            return [{"step_order": 0, "action": "navigate", "selector": None,
                     "value": start_url, "status": "failed", "error": str(e)}]

        for step in steps:
            order    = step.get("step_order", 0)
            action   = step.get("action", "")
            selector = step.get("selector")
            value    = step.get("value")
            url      = step.get("url")
            result   = {"step_order": order, "action": action,
                        "selector": selector, "value": value,
                        "status": "success", "error": None}

            try:
                if action == "navigate":
                    nav_url = value or url
                    if nav_url:
                        page.goto(nav_url, timeout=30000, wait_until="domcontentloaded")

                elif action == "click":
                    if not selector:
                        raise ValueError("No selector for click step")
                    el = page.wait_for_selector(selector, timeout=8000)
                    el.scroll_into_view_if_needed()
                    el.click()
                    # Wait briefly for any navigation / DOM update
                    try:
                        page.wait_for_load_state("domcontentloaded", timeout=5000)
                    except Exception:
                        pass

                elif action == "type":
                    if not selector:
                        raise ValueError("No selector for type step")
                    el = page.wait_for_selector(selector, timeout=8000)
                    el.scroll_into_view_if_needed()
                    el.triple_click()       # select existing text first
                    el.type(value or "", delay=30)

                elif action == "select":
                    if not selector:
                        raise ValueError("No selector for select step")
                    page.select_option(selector, value or "")

                elif action == "scroll":
                    page.mouse.wheel(0, int(value or 300))

                else:
                    result["status"] = "skipped"
                    result["error"] = f"Unknown action: {action}"

            except Exception as e:
                result["status"] = "failed"
                result["error"] = str(e)

            results.append(result)

        browser.close()

    return results


class ReplayService:
    async def replay(self, start_url: str, steps: List[Dict[str, Any]]) -> List[Dict]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, _replay_steps_sync, start_url, steps
        )
