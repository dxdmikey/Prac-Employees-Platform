// Workflow metadata and the demo entity.
//
// The backend decides which actions a user may take; these functions only
// carry the request. Nothing here knows what SUBMIT or APPROVE mean.

import { apiRequest } from './apiClient.js'

// --- definition (platform administration) ---
export function fetchWorkflows() {
  return apiRequest('/api/workflows')
}

/** One workflow with its states and transitions - enough to draw it. */
export function fetchWorkflow(workflowCode) {
  return apiRequest(`/api/workflows/${workflowCode}`)
}

// --- execution (any signed-in user) ---
export function fetchDemoRequests() {
  return apiRequest('/api/workflow-demo')
}

export function createDemoRequest(title, description) {
  return apiRequest('/api/workflow-demo', {
    method: 'POST',
    body: { title, description },
  })
}

/** The actions this user may take on this record, right now. */
export function fetchAvailableTransitions(requestId) {
  return apiRequest(`/api/workflow-demo/${requestId}/available-transitions`)
}

export function executeTransition(requestId, transitionCode, comments) {
  return apiRequest(`/api/workflow-demo/${requestId}/transition`, {
    method: 'POST',
    body: { transition_code: transitionCode, comments },
  })
}

export function fetchHistory(requestId) {
  return apiRequest(`/api/workflow-demo/${requestId}/history`)
}
