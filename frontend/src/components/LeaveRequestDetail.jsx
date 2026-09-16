import { useState } from 'react'
import StateBadge from './StateBadge.jsx'
import { ErrorMessage, Loading } from './StatusViews.jsx'
import { useAsync } from '../hooks/useAsync.js'
import {
  executeTransition,
  fetchAvailableTransitions,
  fetchLeaveHistory,
  formatDate,
} from '../services/leaveService.js'

// One leave request in full: the facts, what you may do to it, and what has
// already happened to it.
//
// The important part is what decides the buttons. This component asks the
// backend "what may this user do to this record right now?" and renders one
// button per answer. It contains no role check, no state name and no list of
// actions - which is why the same component serves the employee who raised
// the request (offered Submit and Cancel on a draft) and the manager deciding
// on it (offered Approve and Reject once it is pending). Hiding a button is
// presentation; the server refuses the action either way.
function LeaveRequestDetail({ request, onChanged, showActions = true, onEdit }) {
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [actionError, setActionError] = useState('')

  const transitionsRequest = useAsync(
    () => (showActions ? fetchAvailableTransitions(request.id) : Promise.resolve([])),
    [request.id, showActions],
  )
  const historyRequest = useAsync(() => fetchLeaveHistory(request.id), [request.id])

  const transitions = transitionsRequest.data ?? []
  const history = historyRequest.data ?? []

  // Two backend answers, and no state name between them:
  //
  //   is_editable    the workflow still allows changes (it is a draft)
  //   transitions    this user has actions here, so this user is the owner
  //
  // Only the owner is ever offered an action while a request is in its first
  // state, so the two together mean "yours, and still a draft". Nothing here
  // knows what that state is called.
  const editable = request.is_editable && transitions.length > 0

  async function handleTransition(transition) {
    setBusy(true)
    setActionError('')
    setMessage('')
    try {
      const updated = await executeTransition(request.id, transition.code)
      setMessage(`${transition.name} done - now ${updated.state_name}.`)
      transitionsRequest.reload()
      historyRequest.reload()
      if (onChanged) onChanged(updated)
    } catch (err) {
      // A refused action is a normal outcome, not a crash. The backend
      // explains which rule said no, and that message is shown as-is.
      setActionError(err.message || 'The action could not be completed.')
    } finally {
      // Always - so a button can never stay stuck on "Working...".
      setBusy(false)
    }
  }

  return (
    <aside className="panel">
      <h2>{request.leave_type.name}</h2>

      <dl className="details">
        <dt>Employee</dt>
        <dd>{request.employee.name}</dd>

        <dt>Business unit</dt>
        <dd>{request.business_unit.name}</dd>

        <dt>Dates</dt>
        <dd>
          {formatDate(request.start_date)} to {formatDate(request.end_date)}
        </dd>

        <dt>Duration</dt>
        <dd>
          {request.total_days} calendar {request.total_days === 1 ? 'day' : 'days'}
        </dd>

        <dt>Status</dt>
        <dd>
          <StateBadge
            code={request.state_code}
            name={request.state_name}
            isFinal={request.is_final}
          />
        </dd>

        <dt>Reason</dt>
        <dd>{request.reason || <span className="muted">Not given</span>}</dd>
      </dl>

      {showActions && (
        <>
          <h3 className="section-heading">Available actions</h3>

          {transitionsRequest.loading && <Loading label="Checking..." />}
          <ErrorMessage
            message={transitionsRequest.error}
            onRetry={transitionsRequest.reload}
          />

          {!transitionsRequest.loading && transitions.length === 0 && (
            <p className="muted small">
              {request.is_final
                ? 'This request is settled. Nothing further can be done to it.'
                : 'You have no actions on this request in its current state. ' +
                  'A request is submitted by the person who raised it and ' +
                  'decided by somebody else.'}
            </p>
          )}

          <div className="row-actions">
            {onEdit && editable && (
              <button
                type="button"
                className="button--secondary button--small"
                disabled={busy}
                onClick={() => onEdit(request)}
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
                  // hardcoded action: anything landing in Rejected or
                  // Cancelled reads as the destructive choice.
                  ['REJECTED', 'CANCELLED'].includes(transition.to_state_code)
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
        </>
      )}

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

export default LeaveRequestDetail
