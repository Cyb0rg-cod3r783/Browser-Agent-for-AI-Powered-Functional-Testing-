// content.js

// Flag to indicate if recording is active in this tab
let isRecordingActive = false;

// Function to get a unique CSS selector for an element
function isStableId(id) {
    if (!id) return false;
    const uuidRegex = /[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}/;
    if (uuidRegex.test(id)) return false;
    if (/\d{4,}/.test(id)) return false;
    if (/\d+$/.test(id) && id.match(/\d+/g).join('').length >= 4) return false;
    return true;
}

function isStableClass(className) {
    if (!className) return false;
    const uuidRegex = /[0-9a-fA-F]{8}-[0-9a-fA-F]{4}/;
    if (uuidRegex.test(className)) return false;
    if (/^[0-9_-]+$/.test(className)) return false;
    
    // Ignore Fluent UI hashed classes and dynamic identifiers
    if (className.startsWith('___')) return false;
    if (/\d/.test(className)) return false; // Reject any class containing numbers (e.g. f22iagw, ftgm304, fui-Input3)
    
    // Ignore generic layout classes
    const genericClasses = ['primitive', 'flex', 'grid', 'wrapper', 'container', 'layout', 'root'];
    const lowerClass = className.toLowerCase();
    for (const gen of genericClasses) {
        if (lowerClass.includes(gen)) return false;
    }
    
    // Reject very short classes
    if (className.length <= 3) return false;
    
    return true;
}

function getCssSelector(el) {
    if (!(el instanceof Element)) return;
    const path = [];
    let current = el;
    while (current && current.nodeType === Node.ELEMENT_NODE) {
        let selector = current.nodeName.toLowerCase();
        
        // 1. Check stable ID
        if (current.id && isStableId(current.id)) {
            selector += '#' + current.id;
            path.unshift(selector);
            break;
        }
        
        // 2. Check other stable attribute combinations (e.g. aria-label, role, contenteditable, name, placeholder, type)
        let hasStableAttr = false;
        const stableAttrs = ['aria-label', 'role', 'contenteditable', 'name', 'placeholder', 'type'];
        for (const attrName of stableAttrs) {
            const attrVal = current.getAttribute(attrName);
            if (attrVal) {
                const uuidRegex = /[0-9a-fA-F]{8}-[0-9a-fA-F]{4}/;
                if (!uuidRegex.test(attrVal) && !/\d{5,}/.test(attrVal)) {
                    selector += `[${attrName}="${attrVal}"]`;
                    hasStableAttr = true;
                }
            }
        }
        
        // 3. If no stable attributes, use classes
        if (!hasStableAttr) {
            let className = '';
            if (current.className && typeof current.className === 'string') {
                const classes = current.className.trim().split(/\s+/)
                    .filter(c => c && !c.includes(':') && isStableClass(c));
                if (classes.length > 0) {
                    className = '.' + classes.join('.');
                    selector += className;
                }
            }
            
            // 4. Fallback to nth-of-type if generic tag
            let sib = current, nth = 1;
            while (sib.previousElementSibling) {
                if (sib.previousElementSibling.nodeName.toLowerCase() === current.nodeName.toLowerCase()) {
                    nth++;
                }
                sib = sib.previousElementSibling;
            }
            if (nth !== 1) {
                selector += `:nth-of-type(${nth})`;
            }
        }
        
        path.unshift(selector);
        
        // 5. Uniqueness optimization: If the selector path built so far uniquely identifies
        // a single element in the document, we can stop immediately to avoid long parent paths.
        const currentFullSelector = path.join(' > ');
        try {
            if (document.querySelectorAll(currentFullSelector).length === 1) {
                return currentFullSelector;
            }
        } catch (e) {
            // Ignore syntax errors in querySelectorAll if any
        }
        
        current = current.parentNode;
    }
    return path.join(' > ');
}

// Function to evaluate XPath and return the first matching element
function evaluateXPath(xpathExpression) {
    try {
        const result = document.evaluate(xpathExpression, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null);
        return result.singleNodeValue;
    } catch (error) {
        console.error('Error evaluating XPath:', xpathExpression, error);
        return null;
    }
}

let recordingIndicator = null;

function showRecordingIndicator() {
    if (!recordingIndicator) {
        recordingIndicator = document.createElement('div');
        recordingIndicator.id = 'workflow-replayer-recording-indicator';
        recordingIndicator.textContent = 'Recording...';
        Object.assign(recordingIndicator.style, {
            position: 'fixed',
            bottom: '0',
            left: '0',
            width: '100%',
            backgroundColor: '#dc3545', // Red background
            color: 'white',
            textAlign: 'center',
            padding: '5px 0',
            fontSize: '14px',
            fontWeight: 'bold',
            zIndex: '99999',
            boxShadow: '0 2px 5px rgba(0,0,0,0.2)',
        });
        document.body.appendChild(recordingIndicator);
    }
}

function hideRecordingIndicator() {
    if (recordingIndicator && recordingIndicator.parentNode) {
        recordingIndicator.parentNode.removeChild(recordingIndicator);
        recordingIndicator = null;
    }
}

// Event listener for clicks
function handleClick(event) {
    if (!isRecordingActive) return;

    let target = event.target;
    
    // 1. Bubble up to the closest contenteditable container
    const contentEditableAncestor = target.closest('[contenteditable="true"]');
    if (contentEditableAncestor) {
        target = contentEditableAncestor;
    } else {
        // 2. Bubble up to the closest interactive element (button, link, or role="button")
        const interactiveAncestor = target.closest('button, a, [role="button"]');
        if (interactiveAncestor) {
            target = interactiveAncestor;
        }
    }

    const selector = getCssSelector(target);
    const elementText = target.innerText.trim().substring(0, 255); // Limit text length
    const elementType = target.tagName.toLowerCase();
    const attributes = {};
    for (let i = 0; i < target.attributes.length; i++) {
        const attr = target.attributes[i];
        if (['id', 'class', 'name', 'href', 'type', 'role', 'aria-label'].includes(attr.name)) {
            attributes[attr.name] = attr.value;
        }
    }

    chrome.runtime.sendMessage({
        type: 'RECORD_ACTION',
        payload: {
            action: 'click',
            selector: selector,
            element_type: elementType,
            element_text: elementText,
            attributes: attributes,
            url: window.location.href,
            value: null // Clicks don't have a value
        }
    });
}

// Helper function to record typing/input actions avoiding duplicate messages
let lastRecordedTypeElement = null;
let lastRecordedTypeValue = null;

function recordTypeAction(target, value) {
    if (!value || !value.trim()) {
        return; // Do not record empty or whitespace-only typing
    }
    if (lastRecordedTypeElement === target && lastRecordedTypeValue === value) {
        return; // Avoid recording duplicate values consecutively
    }
    lastRecordedTypeElement = target;
    lastRecordedTypeValue = value;

    const selector = getCssSelector(target);
    const elementText = target.innerText.trim().substring(0, 255);
    const elementType = target.tagName.toLowerCase();
    const attributes = {};
    for (let i = 0; i < target.attributes.length; i++) {
        const attr = target.attributes[i];
        if (['id', 'class', 'name', 'type', 'placeholder', 'aria-label'].includes(attr.name)) {
            attributes[attr.name] = attr.value;
        }
    }

    chrome.runtime.sendMessage({
        type: 'RECORD_ACTION',
        payload: {
            action: 'type',
            selector: selector,
            element_type: elementType,
            element_text: elementText,
            attributes: attributes,
            url: window.location.href,
            value: value
        }
    });
}

// Event listener for input changes (type)
function handleChange(event) {
    if (!isRecordingActive) return;

    const target = event.target;
    if (target.tagName.toLowerCase() === 'input' || target.tagName.toLowerCase() === 'textarea' || target.tagName.toLowerCase() === 'select') {
        recordTypeAction(target, target.value);
    }
}

// Event listener for blur (to record contenteditable changes when focus is lost)
function handleBlur(event) {
    if (!isRecordingActive) return;

    const target = event.target;
    if (target.isContentEditable) {
        recordTypeAction(target, target.innerText);
    }
}

// Event listener for keydown (to record typing when Enter is pressed)
function handleKeyDown(event) {
    if (!isRecordingActive) return;

    const target = event.target;
    if (event.key === 'Enter' && !event.shiftKey) {
        if (target.isContentEditable) {
            recordTypeAction(target, target.innerText);
        } else if (target.tagName.toLowerCase() === 'input' || target.tagName.toLowerCase() === 'textarea') {
            recordTypeAction(target, target.value);
        }
    }
}

// Event listener for navigation (page load)
function handleNavigation() {
    if (!isRecordingActive) return;

    // Only record navigation for http(s) protocols
    if (!window.location.protocol.startsWith('http')) {
        console.log('Ignoring navigation for non-http(s) protocol:', window.location.href);
        return;
    }

    chrome.runtime.sendMessage({
        type: 'RECORD_ACTION',
        payload: {
            action: 'navigate',
            selector: null,
            element_type: null,
            element_text: null,
            attributes: null,
            url: window.location.href,
            value: window.location.href
        }
    });
}

// Async helper to handle replay action
// Helper to wait for element to appear in DOM, with self-healing fallback
async function waitForElement(selector, timeoutMs = 10000) {
    const startTime = Date.now();
    while (Date.now() - startTime < timeoutMs) {
        let element = document.querySelector(selector);

        // If CSS selector fails or if it looks like an XPath, try XPath
        if (!element && (selector.startsWith('/') || selector.startsWith('('))) {
            element = evaluateXPath(selector);
        }

        // Self-healing selector fallback
        if (!element) {
            // Fallback 1: Try the last attribute selector segment (e.g. div[aria-label="..."])
            const attrMatch = selector.match(/[a-zA-Z0-9_-]+\[[^\]]+\]/g);
            if (attrMatch && attrMatch.length > 0) {
                const fallbackSelector = attrMatch[attrMatch.length - 1];
                try {
                    const candidates = document.querySelectorAll(fallbackSelector);
                    if (candidates.length === 1) {
                        element = candidates[0];
                    } else if (candidates.length > 1) {
                        for (const candidate of candidates) {
                            const rect = candidate.getBoundingClientRect();
                            if (rect.width > 0 && rect.height > 0) {
                                element = candidate;
                                break;
                            }
                        }
                    }
                } catch (e) {}
            }
            
            // Fallback 2: Try the last node segment of the selector path (e.g. p.ck-placeholder)
            if (!element) {
                const segments = selector.split(/\s*>\s*/);
                if (segments.length > 1) {
                    const lastSegment = segments[segments.length - 1];
                    try {
                        const candidates = document.querySelectorAll(lastSegment);
                        if (candidates.length === 1) {
                            element = candidates[0];
                        } else if (candidates.length > 1) {
                            for (const candidate of candidates) {
                                const rect = candidate.getBoundingClientRect();
                                if (rect.width > 0 && rect.height > 0) {
                                    element = candidate;
                                    break;
                                }
                            }
                        }
                    } catch (e) {}
                }
            }
        }

        if (element) {
            return element;
        }
        await new Promise(resolve => setTimeout(resolve, 250)); // Poll every 250ms
    }
    return null;
}

// Async helper to handle replay action
async function handleReplayAction(payload) {
    const { action, selector, value } = payload;
    console.log('Replaying action:', action, 'on selector:', selector, 'with value:', value);
    try {
        const element = await waitForElement(selector, 10000); // Wait up to 10 seconds

        if (element) {
            console.log(`Element found for selector '${selector}'. Tag: ${element.tagName.toLowerCase()}`);
            if (action === 'type') {
                const tag = element.tagName.toLowerCase();
                const isInputOrTextarea = tag === 'input' || tag === 'textarea';
                const isContentEditable = element.isContentEditable;

                if (isInputOrTextarea) {
                    console.log(`Attempting to type '${value}' into input/textarea. Current value: '${element.value}'`);
                    element.focus(); // Simulate focusing the element
                    element.value = value;
                    console.log(`Value set to '${element.value}'. Dispatching events...`);
                    // Add a small delay to ensure value is set before events
                    await new Promise(resolve => setTimeout(resolve, 50));
                    // Dispatch a broader set of events to ensure frameworks react
                    element.dispatchEvent(new Event('input', { bubbles: true }));
                    console.log('Dispatched input event.');
                    element.dispatchEvent(new Event('change', { bubbles: true }));
                    console.log('Dispatched change event.');
                    if (tag === 'input') {
                        element.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true }));
                        element.dispatchEvent(new KeyboardEvent('keyup', { key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true }));
                        console.log('Dispatched Enter key events.');
                    }
                    element.blur(); // Simulate blurring the element
                    console.log('Dispatched blur event.');
                    return { success: true, message: `Autofilled ${selector} with ${value}` };
                } else if (tag === 'select') {
                    console.log(`Setting select dropdown '${selector}' value to '${value}'`);
                    element.focus();
                    element.value = value;
                    await new Promise(resolve => setTimeout(resolve, 50));
                    element.dispatchEvent(new Event('input', { bubbles: true }));
                    element.dispatchEvent(new Event('change', { bubbles: true }));
                    element.blur();
                    return { success: true, message: `Selected option '${value}' in dropdown ${selector}` };
                } else if (isContentEditable) {
                    console.log(`Attempting to type '${value}' into contenteditable element.`);
                    element.focus();
                    
                    // 1. Dispatch beforeinput event
                    try {
                        const beforeInputEvent = new InputEvent('beforeinput', {
                            bubbles: true,
                            cancelable: true,
                            inputType: 'insertText',
                            data: value
                        });
                        element.dispatchEvent(beforeInputEvent);
                    } catch (e) {
                        console.error('Failed to dispatch beforeinput event:', e);
                    }

                    // 2. Set the text
                    try {
                        const selection = window.getSelection();
                        const range = document.createRange();
                        range.selectNodeContents(element);
                        selection.removeAllRanges();
                        selection.addRange(range);
                        if (!document.execCommand('insertText', false, value)) {
                            throw new Error('execCommand insertText failed');
                        }
                    } catch (e) {
                        console.warn('execCommand failed, falling back to innerText:', e);
                        element.innerText = value;
                    }

                    console.log(`innerText set to '${element.innerText}'. Dispatching input events...`);
                    await new Promise(resolve => setTimeout(resolve, 50));
                    
                    // 3. Dispatch input and change events
                    try {
                        const inputEvent = new InputEvent('input', {
                            bubbles: true,
                            cancelable: true,
                            inputType: 'insertText',
                            data: value
                        });
                        element.dispatchEvent(inputEvent);
                    } catch (e) {
                        element.dispatchEvent(new Event('input', { bubbles: true }));
                    }
                    element.dispatchEvent(new Event('change', { bubbles: true }));
                    
                    // 4. Dispatch Enter keys to submit the message
                    const keyEvents = [
                        new KeyboardEvent('keydown', { key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true, cancelable: true }),
                        new KeyboardEvent('keypress', { key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true, cancelable: true }),
                        new KeyboardEvent('keyup', { key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true, cancelable: true })
                    ];
                    for (const ev of keyEvents) {
                        element.dispatchEvent(ev);
                    }
                    console.log('Dispatched events for contenteditable.');
                    element.blur();
                    return { success: true, message: `Typed into contenteditable ${selector} with ${value}` };
                } else {
                    return { success: false, message: `Unsupported element for typing: ${tag}` };
                }
            } else if (action === 'click') {
                console.log(`Attempting to click element with selector '${selector}'.`);
                element.focus();
                
                // Dispatch complete pointer and mouse click sequence
                const clickEvents = [
                    new PointerEvent('pointerdown', { bubbles: true, cancelable: true, pointerType: 'mouse' }),
                    new MouseEvent('mousedown', { bubbles: true, cancelable: true }),
                    new PointerEvent('pointerup', { bubbles: true, cancelable: true, pointerType: 'mouse' }),
                    new MouseEvent('mouseup', { bubbles: true, cancelable: true }),
                    new MouseEvent('click', { bubbles: true, cancelable: true })
                ];
                for (const ev of clickEvents) {
                    element.dispatchEvent(ev);
                }
                return { success: true, message: `Clicked ${selector}` };
            } else if (action === 'navigate') {
                // Navigation is handled by the background script, content script just confirms
                return { success: true, message: `Navigated to ${value}` };
            } else {
                return { success: false, message: `Unsupported replay action: ${action}` };
            }
        } else {
            return { success: false, message: `Element not found for selector: ${selector}` };
        }
    } catch (error) {
        console.error('Error during replay action:', error);
        return { success: false, message: `Error replaying action: ${error.message}` };
    }
}

// Message listener from background script to start/stop recording
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    if (message.type === 'SET_RECORDING_STATUS') {
        isRecordingActive = message.payload.status;
        console.log('Content script recording status:', isRecordingActive);

        if (isRecordingActive) {
            // Add event listeners
            document.addEventListener('click', handleClick, true); // Use capture phase
            document.addEventListener('change', handleChange, true);
            document.addEventListener('blur', handleBlur, true);
            document.addEventListener('keydown', handleKeyDown, true);
            // Initial navigation action when recording starts on a page
            handleNavigation();
            showRecordingIndicator(); // Show indicator when recording starts
        } else {
            // Remove event listeners
            document.removeEventListener('click', handleClick, true);
            document.removeEventListener('change', handleChange, true);
            document.removeEventListener('blur', handleBlur, true);
            document.removeEventListener('keydown', handleKeyDown, true);
            hideRecordingIndicator(); // Hide indicator when recording stops
        }
        sendResponse({ success: true });
    } else if (message.type === 'REPLAY_ACTION') {
        handleReplayAction(message.payload).then(sendResponse);
        return true; // Keep message port open for async response
    }
});

// Initial check for recording status from background script
// This is important if the user navigates to a new page while recording is active
chrome.runtime.sendMessage({ type: 'GET_ACTIVE_WORKFLOW_ID' }, (response) => {
    if (response && response.activeWorkflowId) {
        isRecordingActive = true;
        console.log('Content script initialized with active recording.');
        document.addEventListener('click', handleClick, true);
        document.addEventListener('change', handleChange, true);
        document.addEventListener('blur', handleBlur, true);
        document.addEventListener('keydown', handleKeyDown, true);
        handleNavigation(); // Record navigation on page load if recording is active
        showRecordingIndicator(); // Show indicator if recording is active on load
    }
});