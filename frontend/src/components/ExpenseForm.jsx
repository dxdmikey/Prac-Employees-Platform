import { useState } from 'react'
import { ErrorMessage } from './StatusViews.jsx'
import {
  ACCEPTED_RECEIPT_TYPES,
  MAX_RECEIPT_BYTES,
  formatFileSize,
} from '../services/expenseService.js'

const CURRENCIES = ['USD', 'EUR', 'GBP', 'INR']

// Raise a claim, or edit a draft. One form for both, because the fields match.
//
// The browser checks here are a courtesy. Every rule that matters - a positive
// amount, an active category, a supported currency, and whether this claim is
// still yours to edit - is enforced again on the server, and the message shown
// is the one the server returned.
//
// The receipt is handled separately from the rest of the form, because a file
// upload is a different kind of request: the claim is saved first, and the
// receipt is attached to the claim that now exists.
function ExpenseForm({ expense, categories, onSubmit, onCancel, onAttach }) {
  const editing = Boolean(expense)

  const [values, setValues] = useState({
    category_id: expense?.category?.id ?? '',
    expense_date: expense?.expense_date ?? new Date().toISOString().slice(0, 10),
    amount: expense?.amount ?? '',
    currency: expense?.currency ?? 'USD',
    merchant: expense?.merchant ?? '',
    description: expense?.description ?? '',
    reference_number: expense?.reference_number ?? '',
  })
  const [receipt, setReceipt] = useState(null)
  const [receiptError, setReceiptError] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  function set(field, value) {
    setValues((current) => ({ ...current, [field]: value }))
  }

  function chooseReceipt(file) {
    setReceiptError('')
    if (!file) {
      setReceipt(null)
      return
    }
    // Fail fast with a friendly message rather than making someone wait for an
    // upload that the server is going to refuse anyway.
    if (!ACCEPTED_RECEIPT_TYPES.includes(file.type)) {
      setReceiptError('A receipt must be a JPEG, a PNG or a PDF.')
      setReceipt(null)
      return
    }
    if (file.size > MAX_RECEIPT_BYTES) {
      setReceiptError(
        `That file is ${formatFileSize(file.size)}. The limit is ` +
          `${formatFileSize(MAX_RECEIPT_BYTES)}.`,
      )
      setReceipt(null)
      return
    }
    setReceipt(file)
  }

  async function handleSubmit(event) {
    event.preventDefault()
    setSaving(true)
    setError('')

    const payload = {
      category_id: Number(values.category_id),
      expense_date: values.expense_date,
      amount: values.amount,
      currency: values.currency,
      merchant: values.merchant.trim() || null,
      description: values.description.trim(),
      reference_number: values.reference_number.trim() || null,
    }

    try {
      await onSubmit(payload, receipt)
    } catch (err) {
      setError(err.message || 'The expense could not be saved.')
    } finally {
      // Always - a refused save must never leave the button disabled.
      setSaving(false)
    }
  }

  return (
    <form className="panel" onSubmit={handleSubmit}>
      <h2>{editing ? 'Edit draft expense' : 'New expense'}</h2>

      <div className="form-grid">
        <div>
          <label htmlFor="expense_date">Date</label>
          <input
            id="expense_date"
            type="date"
            value={values.expense_date}
            onChange={(e) => set('expense_date', e.target.value)}
            required
          />
        </div>

        <div>
          <label htmlFor="category_id">Category</label>
          <select
            id="category_id"
            value={values.category_id}
            onChange={(e) => set('category_id', e.target.value)}
            required
          >
            <option value="">Choose a category</option>
            {categories.map((category) => (
              <option key={category.id} value={category.id}>
                {category.name}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label htmlFor="amount">Amount</label>
          <input
            id="amount"
            type="number"
            step="0.01"
            min="0.01"
            value={values.amount}
            placeholder="e.g. 42.50"
            onChange={(e) => set('amount', e.target.value)}
            required
          />
        </div>

        <div>
          <label htmlFor="currency">Currency</label>
          <select
            id="currency"
            value={values.currency}
            onChange={(e) => set('currency', e.target.value)}
          >
            {CURRENCIES.map((code) => (
              <option key={code} value={code}>
                {code}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label htmlFor="merchant">Merchant</label>
          <input
            id="merchant"
            type="text"
            maxLength={200}
            value={values.merchant}
            placeholder="Who you paid"
            onChange={(e) => set('merchant', e.target.value)}
          />
        </div>

        <div>
          <label htmlFor="reference_number">Receipt number</label>
          <input
            id="reference_number"
            type="text"
            maxLength={50}
            value={values.reference_number}
            placeholder="As printed on the receipt"
            onChange={(e) => set('reference_number', e.target.value)}
          />
        </div>
      </div>

      <div className="form-grid">
        <div className="form-grid__wide">
          <label htmlFor="description">Description</label>
          <textarea
            id="description"
            rows={3}
            maxLength={2000}
            value={values.description}
            placeholder="What the money was spent on, and why."
            onChange={(e) => set('description', e.target.value)}
            required
          />
        </div>
      </div>

      {onAttach && (
        <div className="form-grid">
          <div className="form-grid__wide">
            <label htmlFor="receipt">Receipt</label>
            <input
              id="receipt"
              type="file"
              accept={ACCEPTED_RECEIPT_TYPES.join(',')}
              onChange={(e) => chooseReceipt(e.target.files?.[0] ?? null)}
            />
            <p className="muted small">
              {receipt
                ? `${receipt.name} (${formatFileSize(receipt.size)}) will be attached.`
                : `JPEG, PNG or PDF, up to ${formatFileSize(MAX_RECEIPT_BYTES)}. Optional.`}
            </p>
            <ErrorMessage message={receiptError} />
          </div>
        </div>
      )}

      <ErrorMessage message={error} />

      <div className="row-actions">
        <button type="submit" disabled={saving}>
          {saving && <span className="spinner" aria-hidden="true" />}
          {saving ? 'Saving...' : editing ? 'Save draft' : 'Save as draft'}
        </button>
        <button
          type="button"
          className="button--secondary"
          onClick={onCancel}
          disabled={saving}
        >
          Cancel
        </button>
      </div>

      <p className="muted small">
        Saving creates a draft. It is not seen by an approver until you submit
        it.
      </p>
    </form>
  )
}

export default ExpenseForm
