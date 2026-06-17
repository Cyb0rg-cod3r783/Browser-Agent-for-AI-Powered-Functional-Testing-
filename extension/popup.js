// popup.js

document.addEventListener('DOMContentLoaded', () => {
    const startRecordingBtn = document.getElementById('start-recording');
    const stopRecordingBtn = document.getElementById('stop-recording');
    const recordingStatusDiv = document.getElementById('recording-status');
    const recordingWfDetails = document.getElementById('recording-wf-details');
    const recordingStepsCount = document.getElementById('recording-steps-count');
    const workflowListElement = document.getElementById('workflow-list');
    const statusMessageElement = document.getElementById('status-message');
    const clearAllWorkflowsBtn = document.getElementById('clear-all-workflows');

    let currentActiveWorkflowId = null;

    // --- Tab Info Fetching ---
    chrome.tabs.query({ active: true, currentWindow: true }, ([tab]) => {
        const urlElement = document.getElementById('current-url');
        if (tab && tab.url) {
            urlElement.textContent = tab.url;
            urlElement.classList.remove('muted');
        } else {
            urlElement.textContent = 'No active tab or restricted URL';
            urlElement.classList.add('muted');
        }
    });

    // --- UI State Management ---
    function updateRecordingUI(isRecording) {
        if (isRecording) {
            startRecordingBtn.disabled = true;
            stopRecordingBtn.disabled = false;
            recordingStatusDiv.classList.remove('hidden');
            if (currentActiveWorkflowId) {
                recordingWfDetails.textContent = `Workflow #${currentActiveWorkflowId}`;
            }
        } else {
            startRecordingBtn.disabled = false;
            stopRecordingBtn.disabled = true;
            recordingStatusDiv.classList.add('hidden');
        }
    }

    // --- Status Messages ---
    function showStatus(type, title, text) {
        statusMessageElement.className = `status ${type}`;
        const icon = statusMessageElement.querySelector('.status-icon');
        const titleEl = statusMessageElement.querySelector('.status-title');
        const detailEl = statusMessageElement.querySelector('#status-text');
        
        if (icon) icon.textContent = type === 'success' ? '✔' : type === 'error' ? '⚠' : 'ℹ';
        if (titleEl) titleEl.textContent = title;
        if (detailEl) detailEl.textContent = text;
    }

    function clearStatus() {
        statusMessageElement.className = 'status hidden';
    }

    // --- Event Listeners ---
    startRecordingBtn.addEventListener('click', async () => {
        clearStatus();
        try {
            const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
            if (!tab || !tab.url) {
                showStatus('error', 'Tab Error', 'No active tab found.');
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
                showStatus('success', 'Recording Started', `Active Workflow ID: ${currentActiveWorkflowId}`);
                
                // Track step updates periodically
                startPollingStepsCount();
            } else {
                throw new Error(response.error || 'Failed to start recording.');
            }
        } catch (error) {
            console.error('Error starting recording:', error);
            showStatus('error', 'Recording Error', error.message);
            updateRecordingUI(false);
        }
    });

    stopRecordingBtn.addEventListener('click', async () => {
        clearStatus();
        stopPollingStepsCount();
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
                showStatus('success', 'Stopped', 'Recording saved successfully.');
                fetchWorkflows(); // Refresh the list
            } else {
                throw new Error(response.error || 'Failed to stop recording.');
            }
        } catch (error) {
            console.error('Error stopping recording:', error);
            showStatus('error', 'Error Stopping', error.message);
            updateRecordingUI(true); // Keep recording UI active if stop failed
        }
    });

    clearAllWorkflowsBtn.addEventListener('click', async () => {
        if (!confirm('Are you sure you want to delete all recorded workflows? This action cannot be undone.')) {
            return;
        }
        showStatus('info', 'Clearing', 'Deleting all recorded workflows...');
        try {
            const response = await chrome.runtime.sendMessage({ type: 'CLEAR_ALL_WORKFLOWS' });
            if (response.success) {
                showStatus('success', 'Cleared', 'All workflows deleted successfully.');
                fetchWorkflows(); // Refresh the list
            } else {
                throw new Error(response.error || 'Failed to clear all workflows.');
            }
        } catch (error) {
            console.error('Error clearing all workflows:', error);
            showStatus('error', 'Clear Failed', error.message);
        }
    });

    // --- Workflow List and Replay ---
    async function fetchWorkflows() {
        workflowListElement.innerHTML = '<li class="history-empty">Loading workflows...</li>';

        try {
            const response = await chrome.runtime.sendMessage({ type: 'GET_WORKFLOWS' });
            if (response.success) {
                displayWorkflows(response.workflows);
            } else {
                throw new Error(response.error || 'Failed to fetch workflows.');
            }
        } catch (error) {
            console.error('Error fetching workflows:', error);
            showStatus('error', 'Fetch Error', `Could not connect to backend: ${error.message}`);
            workflowListElement.innerHTML = '<li class="history-empty" style="color: var(--red);">Failed to load workflows.</li>';
        }
    }

    function displayWorkflows(workflows) {
        if (workflows.length === 0) {
            workflowListElement.innerHTML = '<li class="history-empty">No workflows recorded yet.</li>';
            return;
        }

        workflowListElement.innerHTML = '';
        workflows.forEach(workflow => {
            const listItem = document.createElement('li');
            listItem.className = 'history-item';
            const workflowName = workflow.name.split(' [')[0]; // Clean up name for display
            const createdAt = new Date(workflow.created_at).toLocaleString();

            listItem.innerHTML = `
                <div class="history-item-top">
                    <span class="history-badge">#${workflow.workflow_id}</span>
                    <span class="history-name" title="${workflowName}">${workflowName}</span>
                    <button data-workflow-id="${workflow.workflow_id}" class="btn-clear" style="padding: 3px 8px; font-size: 11px; font-weight: 700; border-color: var(--accent); color: var(--accent);">Replay</button>
                </div>
                <div class="history-url" title="${workflow.url}">${workflow.url}</div>
                <div class="history-time">${createdAt}</div>
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
        showStatus('info', 'Replaying', `Replaying workflow #${workflowId} inside active tab...`);

        try {
            const response = await chrome.runtime.sendMessage({
                type: 'REPLAY_WORKFLOW',
                payload: { workflowId: workflowId }
            });

            if (response.success) {
                const result = response.result;
                showStatus('success', 'Replay Success', `Status: ${result.status || 'completed'}`);
            } else {
                throw new Error(response.error || 'Failed to replay workflow.');
            }
        } catch (error) {
            console.error('Error replaying workflow:', error);
            showStatus('error', 'Replay Failed', error.message);
        }
    }

    // --- Polling Active Steps count ---
    let pollInterval = null;
    function startPollingStepsCount() {
        if (pollInterval) clearInterval(pollInterval);
        
        const fetchCount = async () => {
            if (!currentActiveWorkflowId) return;
            try {
                const response = await fetch(`http://localhost:8000/api/v1/workflows/${currentActiveWorkflowId}`);
                if (response.ok) {
                    const data = await response.json();
                    const count = data.steps ? data.steps.length : 0;
                    recordingStepsCount.textContent = `${count} action${count !== 1 ? 's' : ''} recorded`;
                }
            } catch (err) {
                console.warn('Error fetching step count:', err);
            }
        };

        fetchCount();
        pollInterval = setInterval(fetchCount, 2000);
    }

    function stopPollingStepsCount() {
        if (pollInterval) {
            clearInterval(pollInterval);
            pollInterval = null;
        }
    }

    // --- Initialization ---
    async function initializePopup() {
        try {
            const response = await chrome.runtime.sendMessage({ type: 'GET_ACTIVE_WORKFLOW_ID' });
            if (response && response.activeWorkflowId) {
                currentActiveWorkflowId = response.activeWorkflowId;
                updateRecordingUI(true);
                startPollingStepsCount();
            } else {
                updateRecordingUI(false);
            }
        } catch (err) {
            console.warn('Failed to fetch active workflow:', err);
            updateRecordingUI(false);
        }
        fetchWorkflows();
    }

    initializePopup();
});