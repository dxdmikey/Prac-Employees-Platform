// Expense Management API calls.
//
// As with leave and timesheets, this file never sends an employee_id and never
// decides which actions are available. Submit, Approve, Reject, Cancel and
// Revise all arrive from fetchAvailableTransitions - the backend's answer for
// this claim, this user, right now - and are posted back through the one
// transition endpoint.

import { apiRequest } from './apiClient.js'

/** The active categories, for the form's dropdown. */
export function fetchCategories() {
  return apiRequest('/api/expenses/categories')
}

/**
 * One page of claims the caller is allowed to see.
 *
 * `pending` asks for claims awaiting a decision. The backend derives that
 * from the workflow metadata rather than from a state name.
 */
export function fetchExpenses({
  page = 1,
  pageSize = 10,
  mine = false,
  pending = false,
  categoryId = '',
  state = '',
  dateFrom = '',
  dateTo = '',
} = {}) {
  const params = new URLSearchParams({ page, page_size: pageSize })
  if (mine) params.set('mine', 'true')
  if (pending) params.set('pending', 'true')
  if (categoryId) params.set('category_id', categoryId)
  if (state) params.set('state', state)
  if (dateFrom) params.set('date_from', dateFrom)
  if (dateTo) params.set('date_to', dateTo)
  return apiRequest(`/api/expenses?${params.toString()}`)
}

export function createExpense(payload) {
  return apiRequest('/api/expenses', { method: 'POST', body: payload })
}

export function updateExpense(expenseId, payload) {
  return apiRequest(`/api/expenses/${expenseId}`, { method: 'PATCH', body: payload })
}

/** The actions this user may take on this claim, right now. */
export function fetchAvailableTransitions(expenseId) {
  return apiRequest(`/api/expenses/${expenseId}/available-transitions`)
}

/** `comments` is where a rejection reason goes; it lands on the history row. */
export function executeTransition(expenseId, transitionCode, comments = null) {
  return apiRequest(`/api/expenses/${expenseId}/transition`, {
    method: 'POST',
    body: { transition_code: transitionCode, comments },
  })
}

export function fetchExpenseHistory(expenseId) {
  return apiRequest(`/api/expenses/${expenseId}/history`)
}

export function fetchExpenseSummary() {
  return apiRequest('/api/expenses/dashboard')
}

// --- receipts ---------------------------------------------------------------

/** Attach a receipt. The browser sets the multipart boundary, so we do not. */
export function uploadReceipt(expenseId, file) {
  const form = new FormData()
  form.append('upload', file)
  return apiRequest(`/api/expenses/${expenseId}/attachments`, {
    method: 'POST',
    body: form,
  })
}

export function deleteReceipt(attachmentId) {
  return apiRequest(`/api/expenses/attachments/${attachmentId}`, { method: 'DELETE' })
}

/**
 * Open a receipt in a new tab.
 *
 * The download endpoint needs the Authorization header, so a plain link would
 * get a 401 - the browser does not attach our bearer token to ordinary
 * navigation. Instead the bytes are fetched with the header, turned into a
 * short-lived object URL, and opened. The URL is revoked afterwards so the
 * blob does not sit in memory for the life of the page.
 */
export async function openReceipt(attachmentId) {
  const response = await apiRequest(
    `/api/expenses/attachments/${attachmentId}/download`,
    { raw: true },
  )
  const blob = await response.blob()
  const url = URL.createObjectURL(blob)
  window.open(url, '_blank', 'noopener')
  // A minute is long enough for the new tab to have loaded it.
  setTimeout(() => URL.revokeObjectURL(url), 60000)
}

// What the backend accepts. Used only to set the file picker's filter and to
// fail fast with a friendly message; the server validates again and is the
// one that decides.
export const ACCEPTED_RECEIPT_TYPES = ['image/jpeg', 'image/png', 'application/pdf']
export const MAX_RECEIPT_BYTES = 5 * 1024 * 1024

/** "1.4 MB", for the receipt list. */
export function formatFileSize(bytes) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

/**
 * Money, formatted with its currency.
 *
 * The amount arrives as a JSON number that the backend produced from an exact
 * Decimal, so the two decimal places are real rather than the result of
 * rounding a float here.
 */
export function formatMoney(amount, currency = 'USD') {
  const value = Number(amount ?? 0)
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency,
    maximumFractionDigits: 2,
  }).format(value)
}
