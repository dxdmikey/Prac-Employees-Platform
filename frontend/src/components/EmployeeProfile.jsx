import { statusLabel } from '../services/employeeService.js'

// An employee's business details.
//
// Only HR fields appear here. Nothing from the authentication side - no
// username, no password hash, no token - is in the API response at all, so
// there is nothing here to accidentally leak.
function StatusBadge({ status }) {
  const modifier =
    status === 'ACTIVE'
      ? 'badge--state-done'
      : status === 'INACTIVE'
        ? 'badge--state-rejected'
        : 'badge--state-open'
  return <span className={`badge ${modifier}`}>{statusLabel(status)}</span>
}

function EmployeeProfile({ employee, onEdit }) {
  return (
    <div className="panel">
      <div className="profile__header">
        <div>
          <h2>{employee.full_name}</h2>
          <p className="muted small">
            {employee.job_title ?? 'No job title recorded'}
          </p>
        </div>
        <StatusBadge status={employee.employment_status} />
      </div>

      <dl className="details">
        <dt>Employee code</dt>
        <dd>
          <code>{employee.employee_code}</code>
        </dd>

        <dt>Email</dt>
        <dd>{employee.email}</dd>

        <dt>Phone</dt>
        <dd>{employee.phone ?? '-'}</dd>

        <dt>Joined</dt>
        <dd>{employee.date_of_joining ?? '-'}</dd>

        <dt>Business unit</dt>
        <dd>{employee.business_unit.name}</dd>

        <dt>Manager</dt>
        <dd>{employee.manager ? employee.manager.name : 'No manager'}</dd>

        <dt>Platform account</dt>
        <dd className="muted">
          {employee.user_id ? 'Linked' : 'None - this person cannot sign in'}
        </dd>
      </dl>

      {onEdit && (
        <div className="row-actions row-actions--stacked">
          <button type="button" className="button--small" onClick={onEdit}>
            Edit
          </button>
        </div>
      )}
    </div>
  )
}

export { StatusBadge }
export default EmployeeProfile
