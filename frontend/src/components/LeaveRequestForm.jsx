import { useState } from 'react'
import { ErrorMessage } from './StatusViews.jsx'
import { previewTotalDays } from '../services/leaveService.js'

// Raise a new leave request, or edit a draft. One form for both, because the
// fields are identical.
//
// The duration shown under the dates is a *preview*. The number that ends up
// in the database is calculated by the server from the same two dates - this
// component never sends a day count, and could not make one stick if it tried.
// Likewise the browser's date validation is a courtesy: an end date before a
// start date is refused again on the server, and the message shown here is
// whatever the server said.
function LeaveRequestForm({ request, leaveTypes, onSubmit, onCancel }) {
  const editing = Boolean(request)

  const [values, setValues] = useState({
    leave_type_id: request?.leave_type?.id ?? '',
    start_date: request?.start_date ?? '',
    end_date: request?.end_date ?? '',
    reason: request?.reason ?? '',
  })
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  function set(field, value) {
    setValues((current) => ({ ...current, [field]: value }))
  }

  const days = previewTotalDays(values.start_date, values.end_date)

  async function handleSubmit(event) {
    event.preventDefault()
    setSaving(true)
    setError('')

    const payload = {
      leave_type_id: Number(values.leave_type_id),
      start_date: values.start_date,
      end_date: values.end_date,
      reason: values.reason.trim() || null,
    }

    try {
      await onSubmit(payload)
    } catch (err) {
      setError(err.message || 'The request could not be saved.')
    } finally {
      // Always - a refused save must never leave the button stuck.
      setSaving(false)
    }
  }

  return (
    <form className="panel" onSubmit={handleSubmit}>
      <h2>{editing ? 'Edit draft request' : 'New leave request'}</h2>

      <div className="form-grid">
        <div>
          <label htmlFor="leave_type_id">Leave type</label>
          <select
            id="leave_type_id"
            value={values.leave_type_id}
            onChange={(e) => set('leave_type_id', e.target.value)}
            required
          >
            <option value="">Choose a type</option>
            {leaveTypes.map((type) => (
              <option key={type.id} value={type.id}>
                {type.name}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label htmlFor="start_date">Start date</label>
          <input
            id="start_date"
            type="date"
            value={values.start_date}
            onChange={(e) => set('start_date', e.target.value)}
            required
          />
        </div>

        <div>
          <label htmlFor="end_date">End date</label>
          <input
            id="end_date"
            type="date"
            value={values.end_date}
            // The browser stops the obvious mistake early; the server stops
            // it properly.
            min={values.start_date || undefined}
            onChange={(e) => set('end_date', e.target.value)}
            required
          />
        </div>

        <div>
          <label htmlFor="total_days_preview">Duration</label>
          <input
            id="total_days_preview"
            type="text"
            readOnly
            // aria-live so a screen reader announces the number changing as
            // the dates are picked, rather than leaving it silent.
            aria-live="polite"
            value={
              days === null
                ? 'Pick both dates'
                : `${days} calendar ${days === 1 ? 'day' : 'days'}`
            }
          />
        </div>
      </div>

      <div className="form-grid">
        <div className="form-grid__wide">
          <label htmlFor="reason">Reason</label>
          <textarea
            id="reason"
            rows={3}
            maxLength={1000}
            value={values.reason}
            placeholder="Why you need the time off. Optional, but it helps your approver."
            onChange={(e) => set('reason', e.target.value)}
          />
        </div>
      </div>

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

export default LeaveRequestForm
