// Leave Management API calls.
//
// Two things this file deliberately does NOT do, because both belong to the
// backend and duplicating them here would be a security hole dressed up as a
// convenience:
//
//   * it never sends an employee_id - the server works out whose leave this is
//     from the signed-in user's linked employee record,
//   * it never sends total_days - the server calculates the duration from the
//     two dates.
//
// It also never decides which buttons a screen may show. That comes from
// fetchAvailableTransitions below, which is the backend's answer for this
// record, this user, right now.

import { apiRequest } from './apiClient.js'

/** The active leave types, for the form's dropdown. */
export function fetchLeaveTypes() {
  return apiRequest('/api/leave/types')
}

/**
 * One page of leave requests the caller is allowed to see.
 *
 * The backend decides what that means - your own requests always, plus
 * anyone inside your business-unit scope if you may approve. There is no
 * "show me everything" parameter, because there is no such view.
 */
export function fetchLeaveRequests({
  page = 1,
  pageSize = 10,
  mine = false,
  pending = false,
  state = '',
} = {}) {
  const params = new URLSearchParams({ page, page_size: pageSize })
  if (mine) params.set('mine', 'true')
  if (pending) params.set('pending', 'true')
  if (state) params.set('state', state)
  return apiRequest(`/api/leave/requests?${params.toString()}`)
}

export function createLeaveRequest(payload) {
  return apiRequest('/api/leave/requests', { method: 'POST', body: payload })
}

export function updateLeaveRequest(requestId, payload) {
  return apiRequest(`/api/leave/requests/${requestId}`, {
    method: 'PUT',
    body: payload,
  })
}

/** The actions this user may take on this request, right now. */
export function fetchAvailableTransitions(requestId) {
  return apiRequest(`/api/leave/requests/${requestId}/available-transitions`)
}

export function executeTransition(requestId, transitionCode, comments = null) {
  return apiRequest(`/api/leave/requests/${requestId}/transition`, {
    method: 'POST',
    body: { transition_code: transitionCode, comments },
  })
}

export function fetchLeaveHistory(requestId) {
  return apiRequest(`/api/leave/requests/${requestId}/history`)
}

/** Headline figures over the requests the caller can see. */
export function fetchLeaveSummary() {
  return apiRequest('/api/leave/dashboard')
}

/**
 * Preview the duration while someone is still typing.
 *
 * This is a mirror of the server's rule - calendar days, both ends included -
 * and exists only so the form can show a number before it is submitted. The
 * value it produces is never sent anywhere: the request body carries the two
 * dates, and the server calculates total_days itself. If the two ever
 * disagree, the server is right.
 */
export function previewTotalDays(startDate, endDate) {
  if (!startDate || !endDate) return null
  const start = new Date(`${startDate}T00:00:00`)
  const end = new Date(`${endDate}T00:00:00`)
  if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) return null
  const days = Math.round((end - start) / 86400000) + 1
  return days > 0 ? days : null
}

/** "2026-09-21" as "21 Sep 2026". */
export function formatDate(isoDate) {
  if (!isoDate) return '-'
  const parsed = new Date(`${isoDate}T00:00:00`)
  if (Number.isNaN(parsed.getTime())) return isoDate
  return parsed.toLocaleDateString('en-GB', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
  })
}
