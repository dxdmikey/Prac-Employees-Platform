// Timesheet API calls.
//
// As with leave, this file never sends an employee_id and never decides which
// actions are available. Submit, Approve, Reject and Revise all arrive from
// fetchAvailableTransitions - the backend's answer for this entry, this user,
// right now - and are posted back through the one transition endpoint.

import { apiRequest } from './apiClient.js'

/**
 * One page of timesheets the caller is allowed to see.
 *
 * `pending` asks for entries awaiting a decision. The backend derives that
 * from the workflow metadata rather than from a state name, so this stays
 * correct if a second review step is ever configured.
 */
export function fetchTimesheets({
  page = 1,
  pageSize = 10,
  mine = false,
  pending = false,
  state = '',
  dateFrom = '',
  dateTo = '',
} = {}) {
  const params = new URLSearchParams({ page, page_size: pageSize })
  if (mine) params.set('mine', 'true')
  if (pending) params.set('pending', 'true')
  if (state) params.set('state', state)
  if (dateFrom) params.set('date_from', dateFrom)
  if (dateTo) params.set('date_to', dateTo)
  return apiRequest(`/api/timesheets?${params.toString()}`)
}

export function createTimesheet(payload) {
  return apiRequest('/api/timesheets', { method: 'POST', body: payload })
}

export function updateTimesheet(timesheetId, payload) {
  return apiRequest(`/api/timesheets/${timesheetId}`, {
    method: 'PATCH',
    body: payload,
  })
}

/** The actions this user may take on this entry, right now. */
export function fetchAvailableTransitions(timesheetId) {
  return apiRequest(`/api/timesheets/${timesheetId}/available-transitions`)
}

export function executeTransition(timesheetId, transitionCode, comments = null) {
  return apiRequest(`/api/timesheets/${timesheetId}/transition`, {
    method: 'POST',
    body: { transition_code: transitionCode, comments },
  })
}

export function fetchTimesheetHistory(timesheetId) {
  return apiRequest(`/api/timesheets/${timesheetId}/history`)
}

export function fetchTimesheetSummary() {
  return apiRequest('/api/timesheets/dashboard')
}

/** "7.5" as "7h 30m", for a table column that has to stay narrow. */
export function formatHours(hours) {
  if (hours === null || hours === undefined) return '-'
  const whole = Math.floor(hours)
  const minutes = Math.round((hours - whole) * 60)
  return minutes === 0 ? `${whole}h` : `${whole}h ${String(minutes).padStart(2, '0')}m`
}
