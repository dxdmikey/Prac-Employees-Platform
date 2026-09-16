import { useState } from 'react'
import { ErrorMessage } from './StatusViews.jsx'
import { EMPLOYMENT_STATUSES, statusLabel } from '../services/employeeService.js'

// Add / edit form, used for both because the fields are the same.
//
// The browser checks are a convenience only. Every rule that matters -
// duplicate codes, unknown business units, self-management, and whether the
// caller may touch that part of the organisation at all - is enforced again on
// the server, and the message shown here is the one the server returned.
function EmployeeForm({ employee, businessUnits, managers, onSubmit, onCancel }) {
  const editing = Boolean(employee)

  const [values, setValues] = useState({
    employee_code: employee?.employee_code ?? '',
    first_name: employee?.first_name ?? '',
    last_name: employee?.last_name ?? '',
    email: employee?.email ?? '',
    phone: employee?.phone ?? '',
    job_title: employee?.job_title ?? '',
    date_of_joining: employee?.date_of_joining ?? '',
    business_unit_id: employee?.business_unit?.id ?? '',
    manager_id: employee?.manager?.id ?? '',
    employment_status: employee?.employment_status ?? 'ACTIVE',
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

    // Empty strings mean "not provided" - send null, or omit for an edit.
    const payload = {
      first_name: values.first_name,
      last_name: values.last_name,
      email: values.email,
      phone: values.phone || null,
      job_title: values.job_title || null,
      date_of_joining: values.date_of_joining || null,
      business_unit_id: Number(values.business_unit_id),
      manager_id: values.manager_id ? Number(values.manager_id) : null,
      employment_status: values.employment_status,
    }
    if (!editing) payload.employee_code = values.employee_code

    try {
      await onSubmit(payload)
    } catch (err) {
      setError(err.message || 'The employee could not be saved.')
    } finally {
      // Always - a rejected save must never leave the button disabled.
      setSaving(false)
    }
  }

  return (
    <form className="panel" onSubmit={handleSubmit}>
      <h2>{editing ? `Edit ${employee.full_name}` : 'Add employee'}</h2>

      <div className="form-grid">
        {!editing && (
          <div>
            <label htmlFor="employee_code">Employee code</label>
            <input
              id="employee_code"
              value={values.employee_code}
              onChange={(e) => set('employee_code', e.target.value)}
              required
            />
          </div>
        )}

        <div>
          <label htmlFor="first_name">First name</label>
          <input
            id="first_name"
            value={values.first_name}
            onChange={(e) => set('first_name', e.target.value)}
            required
          />
        </div>

        <div>
          <label htmlFor="last_name">Last name</label>
          <input
            id="last_name"
            value={values.last_name}
            onChange={(e) => set('last_name', e.target.value)}
            required
          />
        </div>

        <div>
          <label htmlFor="email">Email</label>
          <input
            id="email"
            type="email"
            value={values.email}
            onChange={(e) => set('email', e.target.value)}
            required
          />
        </div>

        <div>
          <label htmlFor="phone">Phone</label>
          <input
            id="phone"
            value={values.phone}
            onChange={(e) => set('phone', e.target.value)}
          />
        </div>

        <div>
          <label htmlFor="job_title">Job title</label>
          <input
            id="job_title"
            value={values.job_title}
            onChange={(e) => set('job_title', e.target.value)}
          />
        </div>

        <div>
          <label htmlFor="date_of_joining">Joining date</label>
          <input
            id="date_of_joining"
            type="date"
            value={values.date_of_joining ?? ''}
            onChange={(e) => set('date_of_joining', e.target.value)}
          />
        </div>

        <div>
          <label htmlFor="business_unit_id">Business unit</label>
          {/* Only units the backend returned - which are only units this
              user may see, so an out-of-scope one cannot be picked. */}
          <select
            id="business_unit_id"
            value={values.business_unit_id}
            onChange={(e) => set('business_unit_id', e.target.value)}
            required
          >
            <option value="">Select...</option>
            {businessUnits.map((unit) => (
              <option key={unit.id} value={unit.id}>
                {unit.name}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label htmlFor="manager_id">Manager</label>
          <select
            id="manager_id"
            value={values.manager_id}
            onChange={(e) => set('manager_id', e.target.value)}
          >
            <option value="">No manager</option>
            {managers
              .filter((m) => m.id !== employee?.id)
              .map((manager) => (
                <option key={manager.id} value={manager.id}>
                  {manager.full_name}
                </option>
              ))}
          </select>
        </div>

        <div>
          <label htmlFor="employment_status">Status</label>
          <select
            id="employment_status"
            value={values.employment_status}
            onChange={(e) => set('employment_status', e.target.value)}
          >
            {EMPLOYMENT_STATUSES.map((status) => (
              <option key={status} value={status}>
                {statusLabel(status)}
              </option>
            ))}
          </select>
        </div>
      </div>

      <ErrorMessage message={error} />

      <div className="row-actions row-actions--stacked">
        <button type="submit" disabled={saving}>
          {saving && <span className="spinner" aria-hidden="true" />}
          {saving ? 'Saving...' : editing ? 'Save changes' : 'Create employee'}
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
    </form>
  )
}

export default EmployeeForm
