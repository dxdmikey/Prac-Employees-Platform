// The organisation hierarchy and user business-unit assignments.
//
// As everywhere else, the backend decides what the caller may see and do -
// these functions just carry the request.

import { apiRequest } from './apiClient.js'

/** The whole organisation, already nested by the backend. */
export function fetchBusinessUnitTree() {
  return apiRequest('/api/business-units/tree')
}

/** Flat list, used to populate the "assign a business unit" dropdown. */
export function fetchBusinessUnits() {
  return apiRequest('/api/business-units')
}

/** Assign a unit. Returns the user's complete new list. */
export function assignBusinessUnit(userId, businessUnitId) {
  return apiRequest(`/api/users/${userId}/business-units`, {
    method: 'POST',
    body: { business_unit_id: businessUnitId },
  })
}

/** Remove an assignment. Returns what remains. */
export function removeBusinessUnit(userId, businessUnitId) {
  return apiRequest(`/api/users/${userId}/business-units/${businessUnitId}`, {
    method: 'DELETE',
  })
}

/** My own scope: what I am assigned, and everything I inherit from it. */
export function fetchMyBusinessUnits() {
  return apiRequest('/api/access/business-units')
}
