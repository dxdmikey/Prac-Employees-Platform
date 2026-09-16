import { useState } from 'react'
import StateBadge from './StateBadge.jsx'
import { ErrorMessage, Loading } from './StatusViews.jsx'
import { useAsync } from '../hooks/useAsync.js'
import { formatDate } from '../services/attendanceService.js'
import {
  executeTransition,
  fetchAvailableTransitions,
  fetchTimesheetHistory,
  formatHours,
} from '../services/timesheetService.js'

// One timesheet entry in full: the facts, what you may do to it, and what has
// already happened to it.
//
// The buttons come from the backend. This component asks "what may this user
// do to this entry right now?" and renders one button per answer, so the same
// component serves the employee who recorded the work (offered Submit on a
// draft, or Revise on a rejected entry) and the manager reviewing it (offered
// Approve and Reject). There is no role check here, and no list of actions.
function TimesheetDetail({ timesheet, onChanged, onEdit }) {
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [actionError, setActionError] = useState('')

  const transitionsRequest = useAsync(
    () => fetchAvailableTransitions(timesheet.id),
    [timesheet.id],
  )
  const historyRequest = useAsync(
    () => fetchTimesheetHistory(timesheet.id),
    [timesheet.id],
  )

  const transitions = transitionsRequest.data ?? []
  const history = historyRequest.data ?? []

  // Two backend answers and no state name between them: the workflow still
  // allows edits, and this user has actions here so this user is the author.
  const editable = timesheet.is_editable && transitions.length > 0

  async function handleTransition(transition) {
    setBusy(true)
    setActionError('')
    setMessage('')
    try {
      const updated = await executeTransition(timesheet.id, transition.code)
      setMessage(`${transition.name} done - now ${updated.state_name}.`)
      transitionsRequest.reload()
      historyRequest.reload()
      if (onChanged) onChanged(updated)
    } catch (err) {
      setActionError(err.message || 'The action could not be completed.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <aside className="panel">
      <h2>{formatDate(timesheet.work_date)}</h2>

      <dl className="details">
        <dt>Employee</dt>
        <dd>{timesheet.employee.name}</dd>

        <dt>Business unit</dt>
        <dd>{timesheet.business_unit.name}</dd>

        <dt>Hours</dt>
        <dd>{formatHours(timesheet.hours)}</dd>

        <dt>Reference</dt>
        <dd>
          {timesheet.reference ? (
            <code className="small">{timesheet.reference}</code>
          ) : (
            <span className="muted">None</span>
          )}
        </dd>

        <dt>Status</dt>
        <dd>
          <StateBadge
            code={timesheet.state_code}
            name={timesheet.state_name}
            isFinal={timesheet.is_final}
          />
        </dd>

        <dt>Work</dt>
        <dd>{timesheet.work_description}</dd>
      </dl>

      <h3 className="section-heading">Available actions</h3>

      {transitionsRequest.loading && <Loading label="Checking..." />}
      <ErrorMessage
        message={transitionsRequest.error}
        onRetry={transitionsRequest.reload}
      />

      {!transitionsRequest.loading && transitions.length === 0 && (
        <p className="muted small">
          {timesheet.is_final
            ? 'This entry is settled. Nothing further can be done to it.'
            : 'You have no actions on this entry in its current state. Work is ' +
              'submitted and revised by the person who recorded it, and ' +
              'approved or rejected by someone else.'}
        </p>
      )}

      <div className="row-actions">
        {onEdit && editable && (
          <button
            type="button"
            className="button--secondary button--small"
            disabled={busy}
            onClick={() => onEdit(timesheet)}
          >
            Edit
          </button>
        )}
        {transitions.map((transition) => (
          <button
            key={transition.code}
            type="button"
            className={
              // Colour follows the destination the metadata names, not a
              // hardcoded action name.
              transition.to_state_code === 'REJECTED'
                ? 'button--danger button--small'
                : 'button--small'
            }
            disabled={busy}
            onClick={() => handleTransition(transition)}
          >
            {busy ? 'Working...' : transition.name}
          </button>
        ))}
      </div>

      {message && (
        <div className="status status--success" role="status">
          {message}
        </div>
      )}
      <ErrorMessage message={actionError} />

      <h3 className="section-heading">History</h3>
      {historyRequest.loading && <Loading label="Loading history..." />}
      <ErrorMessage message={historyRequest.error} onRetry={historyRequest.reload} />
      {!historyRequest.loading && history.length === 0 && (
        <p className="muted small">Nothing recorded yet.</p>
      )}
      <ol className="timeline">
        {history.map((entry) => (
          <li key={entry.id} className="timeline__item">
            <div className="timeline__title">
              {entry.from_state_name
                ? `${entry.from_state_name} → ${entry.to_state_name}`
                : `Created as ${entry.to_state_name}`}
            </div>
            <div className="muted small">
              {entry.transition_name ? `${entry.transition_name} by ` : 'by '}
              {entry.performed_by_username}
              {entry.comments ? ` — ${entry.comments}` : ''}
            </div>
          </li>
        ))}
      </ol>
    </aside>
  )
}

export default TimesheetDetail
