// popup.js

document.addEventListener('DOMContentLoaded', () => {
    const startRecordingBtn = document.getElementById('start-recording');
    const stopRecordingBtn = document.getElementById('stop-recording');
    const recordingStatusDiv = document.getElementById('recording-status');
    const workflowListElement = document.getElementById('workflow-list');
    const statusMessageElement = document.getElementById('status-message');
    const clearAllWorkflowsBtn = document.getElementById('clear-all-workflows');

    let currentActiveWorkflowId = null;

    // --- UI State Management ---
    function updateRecordingUI(isRecording) {
        if (isRecording) {
            startRecordingBtn.disabled = true;
            stopRecordingBtn.disabled = false;
            recordingStatusDiv.textContent = 'Recording active...';
            recordingStatusDiv.classList.add('recording-active');
        } else {
            startRecordingBtn.disabled = false;
            stopRecordingBtn.disabled = true;
            recordingStatusDiv.textContent = '';
            recordingStatusDiv.classList.remove('recording-active');
        }
    }

    // --- Event Listeners ---
    startRecordingBtn.addEventListener('click', async () => {
        statusMessageElement.textContent = ''; // Clear general status
        try {
            const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
            if (!tab || !tab.url) {
                statusMessageElement.textContent = 'Error: No active tab found.';
                statusMessageElement.classList.add('error-message');
                return;
            }

            // Send message to background script to start recording
            const response = await chrome.runtime.sendMessage({
                type: 'START_RECORDING',
                payload: { url: tab.url }
            });

            if (response.success) {
                currentActiveWorkflowId = response.workflowId;
                updateRecordingUI(true);
                // Send message directly to content script in the active tab
                try {
                    await chrome.tabs.sendMessage(tab.id, { type: 'SET_RECORDING_STATUS', payload: { status: true } });
                } catch (err) {
                    console.log('Content script not present, injecting content.js...');
                    try {
                        await chrome.scripting.executeScript({
                            target: { tabId: tab.id },
                            files: ['content.js']
                        });
                        // Wait a moment for injection to complete, then send message
                        await new Promise(resolve => setTimeout(resolve, 100));
                        await chrome.tabs.sendMessage(tab.id, { type: 'SET_RECORDING_STATUS', payload: { status: true } });
                    } catch (scriptErr) {
                        console.error('Failed to inject or notify content script:', scriptErr);
                    }
                }
                statusMessageElement.textContent = `Recording started for Workflow ID: ${currentActiveWorkflowId}`;
                statusMessageElement.classList.remove('error-message');
            } else {
                throw new Error(response.error || 'Failed to start recording.');
            }
        } catch (error) {
            console.error('Error starting recording:', error);
            statusMessageElement.textContent = `Error starting recording: ${error.message}`;
            statusMessageElement.classList.add('error-message');
            updateRecordingUI(false);
        }
    });

    stopRecordingBtn.addEventListener('click', async () => {
        statusMessageElement.textContent = ''; // Clear general status
        try {
            const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });

            // Send message to background script to stop recording
            const response = await chrome.runtime.sendMessage({ type: 'STOP_RECORDING' });

            if (response.success) {
                updateRecordingUI(false);
                currentActiveWorkflowId = null;
                // Instruct content script to stop listening
                if (tab && tab.id) {
                    try {
                        await chrome.tabs.sendMessage(tab.id, { type: 'SET_RECORDING_STATUS', payload: { status: false } });
                    } catch (err) {
                        console.warn('Could not send STOP message to content script:', err);
                    }
                }
                statusMessageElement.textContent = 'Recording stopped. Refreshing workflows...';
                statusMessageElement.classList.remove('error-message');
                fetchWorkflows(); // Refresh the list to show the new workflow
            } else {
                throw new Error(response.error || 'Failed to stop recording.');
            }
        } catch (error) {
            console.error('Error stopping recording:', error);
            statusMessageElement.textContent = `Error stopping recording: ${error.message}`;
            statusMessageElement.classList.add('error-message');
            updateRecordingUI(true); // Keep recording UI active if stop failed
        }
    });

    clearAllWorkflowsBtn.addEventListener('click', async () => {
        if (!confirm('Are you sure you want to delete all recorded workflows? This action cannot be undone.')) {
            return;
        }
        statusMessageElement.textContent = 'Clearing all workflows...';
        statusMessageElement.classList.remove('error-message');
        try {
            const response = await chrome.runtime.sendMessage({ type: 'CLEAR_ALL_WORKFLOWS' });
            if (response.success) {
                statusMessageElement.textContent = 'All workflows cleared successfully.';
                statusMessageElement.classList.add('success-message');
                fetchWorkflows(); // Refresh the list
            } else {
                throw new Error(response.error || 'Failed to clear all workflows.');
            }
        } catch (error) {
            console.error('Error clearing all workflows:', error);
            statusMessageElement.textContent = `Error clearing workflows: ${error.message}`;
            statusMessageElement.classList.add('error-message');
        }
    });

    // --- Workflow List and Replay ---
    async function fetchWorkflows() {
        statusMessageElement.textContent = 'Loading workflows...';
        statusMessageElement.classList.remove('error-message');
        workflowListElement.innerHTML = ''; // Clear previous list

        try {
            const response = await chrome.runtime.sendMessage({ type: 'GET_WORKFLOWS' });
            if (response.success) {
                displayWorkflows(response.workflows);
                statusMessageElement.textContent = ''; // Clear status message on success
            } else {
                throw new Error(response.error || 'Failed to fetch workflows.');
            }
        } catch (error) {
            console.error('Error fetching workflows:', error);
            statusMessageElement.textContent = `Error: Could not connect to backend or fetch workflows. Is the backend running? (${error.message})`;
            statusMessageElement.classList.add('error-message');
        }
    }

    function displayWorkflows(workflows) {
        if (workflows.length === 0) {
            workflowListElement.innerHTML = '<li>No workflows recorded yet.</li>';
            return;
        }

        workflows.forEach(workflow => {
            const listItem = document.createElement('li');
            const workflowName = workflow.name.split(' [')[0]; // Clean up name for display
            const createdAt = new Date(workflow.created_at).toLocaleString();

            listItem.innerHTML = `
                <span>${workflowName} <br> <small>ID: ${workflow.workflow_id} | ${createdAt}</small></span>
                <button data-workflow-id="${workflow.workflow_id}">Replay</button>
            `;
            workflowListElement.appendChild(listItem);
        });

        workflowListElement.querySelectorAll('button').forEach(button => {
            button.addEventListener('click', (event) => {
                const workflowId = event.target.dataset.workflowId;
                replayWorkflow(workflowId);
            });
        });
    }

    async function replayWorkflow(workflowId) {
        statusMessageElement.textContent = `Initiating replay for Workflow ID: ${workflowId}...`;
        statusMessageElement.classList.remove('error-message');

        try {
            const response = await chrome.runtime.sendMessage({
                type: 'REPLAY_WORKFLOW',
                payload: { workflowId: workflowId }
            });

            if (response.success) {
                const result = response.result;
                statusMessageElement.textContent = `Replay completed with status: ${result.status}!`;
                statusMessageElement.classList.remove('error-message');
                if (result.status !== 'completed') {
                    statusMessageElement.classList.add('error-message');
                }
            } else {
                throw new Error(response.error || 'Failed to replay workflow.');
            }
        } catch (error) {
            console.error('Error replaying workflow:', error);
            statusMessageElement.textContent = `Replay failed: ${error.message}`;
            statusMessageElement.classList.add('error-message');
        }
    }

    // --- Initialization ---
    async function initializePopup() {
        // Check if recording is already active (e.g., if popup was closed and reopened)
        const response = await chrome.runtime.sendMessage({ type: 'GET_ACTIVE_WORKFLOW_ID' });
        if (response && response.activeWorkflowId) {
            currentActiveWorkflowId = response.activeWorkflowId;
            updateRecordingUI(true);
            recordingStatusDiv.textContent = `Recording active (Workflow ID: ${currentActiveWorkflowId})...`;
            recordingStatusDiv.classList.add('recording-active');
        } else {
            updateRecordingUI(false);
        }
        fetchWorkflows();
    }

    initializePopup();
});