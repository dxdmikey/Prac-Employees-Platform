// The one place the frontend talks to the backend.
//
// Every request in the app goes through here, which means the timeout, the
// Authorization header and the error messages are written once and behave the
// same everywhere. A component should never call fetch() directly.

import { API_BASE_URL } from '../config/api.js'

// How long we wait for the backend before giving up, in milliseconds.
//
// Without this, a backend that accepts the connection but never answers - a
// crashed or wedged server still holding the port - leaves fetch() pending
// forever. The promise never settles, the caller's "finally" never runs, and a
// button stays stuck on "Saving..." with no explanation. This is exactly the
// bug that stalled the login page, so every request is bounded.
const REQUEST_TIMEOUT_MS = 10000

const TOKEN_KEY = 'employee-platform-token'

export function getToken() {
  return localStorage.getItem(TOKEN_KEY)
}

export function saveToken(token) {
  localStorage.setItem(TOKEN_KEY, token)
}

export function clearToken() {
  localStorage.removeItem(TOKEN_KEY)
}

// Thrown for any failed request. Carrying the HTTP status lets callers react
// to specific cases - the app treats 401 as "your session ended".
export class ApiError extends Error {
  constructor(message, status) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

async function readErrorMessage(response, fallback) {
  try {
    const body = await response.json()
    // FastAPI puts the message in "detail", which is either a string or,
    // for validation errors, a list of objects.
    if (typeof body.detail === 'string') return body.detail
    if (Array.isArray(body.detail) && body.detail[0]?.msg) return body.detail[0].msg
    if (typeof body.detail?.reason === 'string') return body.detail.reason
  } catch {
    // No JSON body - fall through to the generic message.
  }
  return fallback
}

/**
 * Make a request to the backend.
 *
 * @param {string} path      e.g. "/api/access/me"
 * @param {object} options   method, body (a plain object), auth (default true)
 */
export async function apiRequest(path, { method = 'GET', body, auth = true } = {}) {
  const headers = {}
  if (body !== undefined) headers['Content-Type'] = 'application/json'

  if (auth) {
    const token = getToken()
    // This header is how the backend recognises us on every request.
    if (token) headers.Authorization = `Bearer ${token}`
  }

  let response
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
    })
  } catch (err) {
    if (err.name === 'TimeoutError' || err.name === 'AbortError') {
      throw new ApiError(
        `The server at ${API_BASE_URL} did not respond. Is the backend running?`,
        0,
      )
    }
    // fetch rejects with a TypeError when the connection fails outright, which
    // also covers a request the browser blocked for CORS reasons.
    throw new ApiError(
      `Could not reach the server at ${API_BASE_URL}. Check that the backend is ` +
        'running and that this origin is allowed by its CORS settings.',
      0,
    )
  }

  if (!response.ok) {
    throw new ApiError(
      await readErrorMessage(response, `Request failed (HTTP ${response.status}).`),
      response.status,
    )
  }

  // 204 No Content has no body to parse.
  if (response.status === 204) return null
  return response.json()
}
