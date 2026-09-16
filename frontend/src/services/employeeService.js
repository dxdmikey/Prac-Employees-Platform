// Employee Management API calls.
//
// The backend scopes every response to the caller's business units, so these
// functions never send anything about "who am I" - the token already says.

import { apiRequest } from './apiClient.js'

/** One page of employees. Filters are optional; unset ones are omitted. */
export function fetchEmployees({
  page = 1,
  pageSize = 10,
  search = '',
  businessUnitId = '',
  employmentStatus = '',
} = {}) {
  const params = new URLSearchParams({ page, page_size: pageSize })
  if (search.trim()) params.set('search', search.trim())
  if (businessUnitId) params.set('business_unit_id', businessUnitId)
  if (employmentStatus) params.set('employment_status', employmentStatus)
  return apiRequest(`/api/employees?${params.toString()}`)
}

export function createEmployee(payload) {
  return apiRequest('/api/employees', { method: 'POST', body: payload })
}

export function updateEmployee(employeeId, payload) {
  return apiRequest(`/api/employees/${employeeId}`, { method: 'PUT', body: payload })
}

export const EMPLOYMENT_STATUSES = ['ACTIVE', 'INACTIVE', 'ON_LEAVE']

/** Turn ON_LEAVE into "On Leave" for display. */
export function statusLabel(status) {
  return status
    .split('_')
    .map((word) => word[0] + word.slice(1).toLowerCase())
    .join(' ')
}
