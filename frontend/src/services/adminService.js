// Platform administration calls.
//
// The backend refuses every one of these unless the caller has access to the
// matching platform-admin application, so hiding the Administration tab in the
// UI is a convenience, not the security boundary.

import { apiRequest } from './apiClient.js'

export function fetchUsers() {
  return apiRequest('/api/users')
}

export function fetchRoles() {
  return apiRequest('/api/roles')
}

/** Assign a role. Returns the user's complete new role list. */
export function assignRole(userId, roleId) {
  return apiRequest(`/api/users/${userId}/roles`, {
    method: 'POST',
    body: { role_id: roleId },
  })
}

/** Remove a role. Returns the user's remaining roles. */
export function removeRole(userId, roleId) {
  return apiRequest(`/api/users/${userId}/roles/${roleId}`, { method: 'DELETE' })
}
