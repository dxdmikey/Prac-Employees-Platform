// Attendance API calls.
//
// Nothing here decides anything. In particular the Check In and Check Out
// buttons are not drawn from timestamps this file inspects - the backend
// returns can_check_in and can_check_out, because it is the backend that will
// refuse the action, and the two must agree.

import { apiRequest } from './apiClient.js'

/** Today's own record, plus whether checking in or out is possible now. */
export function fetchToday() {
  return apiRequest('/api/attendance/today')
}

export function checkIn() {
  return apiRequest('/api/attendance/check-in', { method: 'POST' })
}

export function checkOut() {
  return apiRequest('/api/attendance/check-out', { method: 'POST' })
}

/** The signed-in user's own recent days, newest first. */
export function fetchMyHistory(days = 30) {
  return apiRequest(`/api/attendance/history?days=${days}`)
}

/**
 * One page of attendance the caller is allowed to see.
 *
 * There is no "show everything" parameter, because there is no such view: the
 * backend returns your own records plus anyone in your business-unit scope you
 * may approve for, and every filter below narrows that set rather than
 * widening it.
 */
export function fetchAttendance({
  page = 1,
  pageSize = 10,
  mine = false,
  employeeId = '',
  attendanceStatus = '',
  dateFrom = '',
  dateTo = '',
  openOnly = false,
} = {}) {
  const params = new URLSearchParams({ page, page_size: pageSize })
  if (mine) params.set('mine', 'true')
  if (employeeId) params.set('employee_id', employeeId)
  if (attendanceStatus) params.set('attendance_status', attendanceStatus)
  if (dateFrom) params.set('date_from', dateFrom)
  if (dateTo) params.set('date_to', dateTo)
  if (openOnly) params.set('open_only', 'true')
  return apiRequest(`/api/attendance?${params.toString()}`)
}

/** Amend a day. Refused with 403 unless the caller holds the EDIT permission. */
export function correctAttendance(recordId, payload) {
  return apiRequest(`/api/attendance/${recordId}`, { method: 'PATCH', body: payload })
}

export function fetchAttendanceSummary() {
  return apiRequest('/api/attendance/dashboard')
}

// The statuses the backend accepts. Listed here only to build a filter
// dropdown; no screen branches on them to decide what a user may do.
export const ATTENDANCE_STATUSES = [
  'PRESENT',
  'HALF_DAY',
  'INCOMPLETE',
  'ON_LEAVE',
  'ABSENT',
]

/** Turn HALF_DAY into "Half Day" for display. */
export function statusLabel(status) {
  return status
    .split('_')
    .map((word) => word[0] + word.slice(1).toLowerCase())
    .join(' ')
}

/** "2026-09-16" as "16 Sep 2026". */
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

/** A timestamp as a wall-clock time, "09:14". Empty timestamps show a dash. */
export function formatTime(isoTimestamp) {
  if (!isoTimestamp) return '-'
  const parsed = new Date(isoTimestamp)
  if (Number.isNaN(parsed.getTime())) return '-'
  return parsed.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })
}

/**
 * Worked time as "7h 45m".
 *
 * The backend sends both minutes and hours; minutes are used here because
 * "7h 45m" reads better on a timesheet than "7.75".
 */
export function formatDuration(minutes) {
  if (minutes === null || minutes === undefined) return '-'
  const hours = Math.floor(minutes / 60)
  const rest = minutes % 60
  return hours === 0 ? `${rest}m` : `${hours}h ${String(rest).padStart(2, '0')}m`
}
