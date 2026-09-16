import { useState } from 'react'
import { ErrorMessage } from './StatusViews.jsx'

// Record work, or edit a draft. One form for both, because the fields are the
// same.
//
// Hours are what a person types; the backend converts them to minutes and
// stores those, so a quarter of an hour stays exact rather than becoming
// 0.25 of something. The browser checks below are a courtesy - every rule
// that matters is enforced again on the server, and the message shown here is
// whatever the server returned.
function TimesheetForm({ timesheet, onSubmit, onCancel }) {
  const editing = Boolean(timesheet)

  const [values, setValues] = useState({
    work_date: timesheet?.work_date ?? new Date().toISOString().slice(0, 10),
    hours: timesheet?.hours ?? '',
    work_description: timesheet?.work_description ?? '',
    reference: timesheet?.reference ?? '',
  })
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  function set(field, value) {
    setValues((current) => ({ ...current, [field]: value }))
  }

  async function handleSubmit(event) {
    event.preventDefault()
    setSaving(true)
    setError('')

    const payload = {
      work_date: values.work_date,
      hours: Number(values.hours),
      work_description: values.work_description.trim(),
      reference: values.reference.trim() || null,
    }

    try {
      await onSubmit(payload)
    } catch (err) {
      setError(err.message || 'The entry could not be saved.')
    } finally {
      // Always - a rejected save must never leave the button disabled.
      setSaving(false)
    }
  }

  return (
    <form className="panel" onSubmit={handleSubmit}>
      <h2>{editing ? 'Edit draft entry' : 'Record work'}</h2>

      <div className="form-grid">
        <div>
          <label htmlFor="work_date">Date</label>
          <input
            id="work_date"
            type="date"
            value={values.work_date}
            onChange={(e) => set('work_date', e.target.value)}
            required
          />
        </div>

        <div>
          <label htmlFor="hours">Hours</label>
          <input
            id="hours"
            type="number"
            step="0.25"
            min="0.25"
            max="24"
            value={values.hours}
            placeholder="e.g. 7.5"
            onChange={(e) => set('hours', e.target.value)}
            required
          />
        </div>

        <div>
          <label htmlFor="reference">Reference</label>
          <input
            id="reference"
            type="text"
            maxLength={100}
            value={values.reference}
            placeholder="Project or ticket, optional"
            onChange={(e) => set('reference', e.target.value)}
          />
        </div>
      </div>

      <div className="form-grid">
        <div className="form-grid__wide">
          <label htmlFor="work_description">What did you work on?</label>
          <textarea
            id="work_description"
            rows={3}
            maxLength={2000}
            value={values.work_description}
            placeholder="Enough detail for your approver to recognise the work."
            onChange={(e) => set('work_description', e.target.value)}
            required
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

export default TimesheetForm
