// background.js

let activeWorkflowId = null; // Stores the ID of the currently recording workflow

// Function to send actions to the backend
async function sendActionToBackend(actionData) {
    if (!activeWorkflowId) {
        console.warn("No active workflow to record actions for.");
        return;
    }

    try {
        const response = await fetch('http://localhost:8000/api/v1/record/action', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                workflow_id: activeWorkflowId,
                ...actionData
            }),
        });

        if (!response.ok) {
            const errorText = await response.text();
            throw new Error(`Backend record action failed: ${response.status} - ${errorText}`);
        }
        const result = await response.json();
        console.log('Action recorded:', result);
    } catch (error) {
        console.error('Error sending action to backend:', error);
    }
}

// Listener for messages from content scripts (user actions)
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    if (message.type === 'RECORD_ACTION') {
        sendActionToBackend(message.payload);
    }
    // You can add other message types here if needed
});

// Listener for messages from popup.js (start/stop recording, replay)
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    switch (message.type) {
        case 'START_RECORDING':
            startRecordingWorkflow(message.payload.url).then(workflowId => {
                sendResponse({ success: true, workflowId: workflowId });
            }).catch(error => {
                sendResponse({ success: false, error: error.message });
            });
            return true; // Indicate that sendResponse will be called asynchronously

        case 'STOP_RECORDING':
            stopRecordingWorkflow().then(() => {
                sendResponse({ success: true });
            }).catch(error => {
                sendResponse({ success: false, error: error.message });
            });
            return true; // Indicate that sendResponse will be called asynchronously

        case 'REPLAY_WORKFLOW':
            replayWorkflow(message.payload.workflowId).then(result => {
                sendResponse({ success: true, result: result });
            }).catch(error => {
                sendResponse({ success: false, error: error.message });
            });
            return true; // Indicate that sendResponse will be called asynchronously

        case 'GET_ACTIVE_WORKFLOW_ID':
            sendResponse({ activeWorkflowId: activeWorkflowId });
            break;

        case 'GET_WORKFLOWS':
            getWorkflows().then(workflows => {
                sendResponse({ success: true, workflows: workflows });
            }).catch(error => {
                sendResponse({ success: false, error: error.message });
            });
            return true; // Indicate that sendResponse will be called asynchronously

        case 'CLEAR_ALL_WORKFLOWS':
            clearAllWorkflows().then(() => {
                sendResponse({ success: true });
            }).catch(error => {
                sendResponse({ success: false, error: error.message });
            });
            return true; // Indicate that sendResponse will be called asynchronously
    }
});

// Function to start a new recording workflow
async function startRecordingWorkflow(url) {
    // Validate URL before sending to backend
    if (!url || (!url.startsWith('http://') && !url.startsWith('https://'))) {
        throw new Error('Recording can only start on valid web pages (http:// or https://).');
    }

    try {
        const response = await fetch('http://localhost:8000/api/v1/record/start', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ url: url }),
        });

        if (!response.ok) {
            const errorText = await response.text();
            throw new Error(`Backend start recording failed: ${response.status} - ${errorText}`);
        }
        const result = await response.json();
        activeWorkflowId = result.workflow_id;
        console.log('Recording started, Workflow ID:', activeWorkflowId);
        // Store in local storage so popup can retrieve it
        await chrome.storage.local.set({ activeWorkflowId: activeWorkflowId });
        return activeWorkflowId;
    } catch (error) {
        console.error('Error starting recording:', error);
        throw error;
    }
}

// Function to stop the current recording workflow
async function stopRecordingWorkflow() {
    if (!activeWorkflowId) {
        console.warn("No active workflow to stop.");
        return;
    }

    try {
        const response = await fetch('http://localhost:8000/api/v1/record/stop', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ workflow_id: activeWorkflowId }),
        });

        if (!response.ok) {
            const errorText = await response.text();
            throw new Error(`Backend stop recording failed: ${response.status} - ${errorText}`);
        }
        const result = await response.json();
        console.log('Recording stopped:', result);
        activeWorkflowId = null;
        await chrome.storage.local.remove('activeWorkflowId'); // Clear from storage
    } catch (error) {
        console.error('Error stopping recording:', error);
        throw error;
    }
}

// Function to replay a workflow
async function replayWorkflow(workflowId) {
    try {
        // Fetch the workflow details from the backend to get the steps
        const response = await fetch(`http://localhost:8000/api/v1/workflows/${workflowId}`, {
            method: 'GET',
            headers: {
                'Content-Type': 'application/json',
            },
        });

        if (!response.ok) {
            const errorText = await response.text();
            throw new Error(`Backend fetch workflow failed: ${response.status} - ${errorText}`);
        }
        const workflowDetail = await response.json();
        const replaySteps = workflowDetail.steps || []; // This is the list of actions to replay

        console.log('Replaying workflow steps:', replaySteps);

        // Get the currently active tab to perform actions
        const [activeTab] = await chrome.tabs.query({ active: true, currentWindow: true });
        if (!activeTab) {
            throw new Error("No active tab found to replay workflow.");
        }

        for (const step of replaySteps) {
            console.log('Processing step:', step);
            if (step.action === 'navigate') {
                // Navigate to the URL
                await chrome.tabs.update(activeTab.id, { url: step.value });
                // Wait for the page to load before proceeding
                await new Promise(resolve => {
                    chrome.tabs.onUpdated.addListener(function listener(tabId, changeInfo) {
                        if (tabId === activeTab.id && changeInfo.status === 'complete') {
                            chrome.tabs.onUpdated.removeListener(listener);
                            resolve();
                        }
                    });
                });
                // Add a small delay after navigation to ensure content script is ready
                await new Promise(resolve => setTimeout(resolve, 1000)); // Add 1 second delay
            } else if (step.action === 'type' || step.action === 'click') {
                // Send message to content script to perform the action
                const contentResponse = await chrome.tabs.sendMessage(activeTab.id, {
                    type: 'REPLAY_ACTION',
                    payload: {
                        action: step.action,
                        selector: step.selector,
                        value: step.value // This will be used for 'type' actions
                    }
                });
                if (!contentResponse || !contentResponse.success) {
                    console.error('Content script failed to replay action:', contentResponse ? contentResponse.message : 'No response');
                    // Throw an error to stop replay if content script failed
                    throw new Error(`Failed to replay action: ${step.action} on ${step.selector}. Content script response: ${contentResponse ? contentResponse.message : 'No response'}`);
                }
                // Add a small delay between actions to simulate user interaction
                await new Promise(resolve => setTimeout(resolve, 500));
            }
        }

        return { status: 'completed', message: 'Workflow replayed successfully.' };

    } catch (error) {
        console.error('Error replaying workflow:', error);
        throw error;
    }
}

// Function to get all workflows
async function getWorkflows() {
    try {
        const response = await fetch('http://localhost:8000/api/v1/workflows');
        if (!response.ok) {
            const errorText = await response.text();
            throw new Error(`Backend get workflows failed: ${response.status} - ${errorText}`);
        }
        const workflows = await response.json();
        return workflows;
    } catch (error) {
        console.error('Error fetching workflows:', error);
        throw error;
    }
}

// Function to clear all workflows
async function clearAllWorkflows() {
    try {
        const response = await fetch('http://localhost:8000/api/v1/workflows/clear_all', {
            method: 'DELETE',
        });

        if (!response.ok) {
            const errorText = await response.text();
            throw new Error(`Backend clear all workflows failed: ${response.status} - ${errorText}`);
        }
        console.log('All workflows cleared.');
    } catch (error) {
        console.error('Error clearing all workflows:', error);
        throw error;
    }
}

// Initialize activeWorkflowId from storage when background script starts
chrome.storage.local.get('activeWorkflowId', (data) => {
    if (data.activeWorkflowId) {
        activeWorkflowId = data.activeWorkflowId;
        console.log('Restored active workflow ID:', activeWorkflowId);
    }
});