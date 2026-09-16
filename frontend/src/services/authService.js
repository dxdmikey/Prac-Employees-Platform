// Authentication calls. All networking goes through apiClient.

import { ApiError, apiRequest, clearToken, getToken, saveToken } from './apiClient.js'

export { getToken, clearToken }

export async function login(username, password) {
  const data = await apiRequest('/api/auth/login', {
    method: 'POST',
    body: { username, password },
    auth: false, // there is no token yet - that is the point of this call
  })
  saveToken(data.access_token)
  return data.user
}

export async function fetchCurrentUser() {
  if (!getToken()) return null

  try {
    return await apiRequest('/api/auth/me')
  } catch (err) {
    // 401 means the token expired, was revoked by logout elsewhere, or the
    // account was deactivated. Drop it and show the login page.
    if (err instanceof ApiError && err.status === 401) {
      clearToken()
      return null
    }
    throw err
  }
}

export async function logout() {
  if (getToken()) {
    try {
      // Tell the backend to delete the token so it cannot be reused.
      await apiRequest('/api/auth/logout', { method: 'POST' })
    } catch {
      // Even if the backend is unreachable, still log out locally below.
    }
  }
  clearToken()
}
