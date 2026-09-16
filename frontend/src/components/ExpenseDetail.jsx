import { useState } from 'react'
import StateBadge from './StateBadge.jsx'
import { ErrorMessage, Loading } from './StatusViews.jsx'
import { useAsync } from '../hooks/useAsync.js'
import { formatDate } from '../services/attendanceService.js'
import {
  deleteReceipt,
  executeTransition,
  fetchAvailableTransitions,
  fetchExpenseHistory,
  formatFileSize,
  formatMoney,
  openReceipt,
} from '../services/expenseService.js'

// One claim in full: the facts, its receipts, what you may do to it, and what
// has already happened to it.
//
// The buttons come from the backend. This component asks "what may this user
// do to this claim right now?" and renders one button per answer, so the same
// component serves the employee who raised it (offered Submit on a draft,
// Cancel once submitted, Revise once rejected) and the manager reviewing it
// (offered Approve and Reject). There is no role check here.
//
// Rejecting asks for a reason first. The reason is stored on the workflow
// history row rather than on the claim, because it explains a decision rather
// than describing the expense.
function ExpenseDetail({ expense, onChanged, onEdit }) {
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [actionError, setActionError] = useState('')
  const [reasonFor, setReasonFor] = useState(null)
  const [reason, setReason] = useState('')

  const transitionsRequest = useAsync(
    () => fetchAvailableTransitions(expense.id),
    [expense.id],
  )
  const historyRequest = useAsync(() => fetchExpenseHistory(expense.id), [expense.id])

  const transitions = transitionsRequest.data ?? []
  const history = historyRequest.data ?? []

  // Two backend answers and no state name between them: the workflow still
  // allows edits, and this user has actions here so this user is the owner.
  const editable = expense.is_editable && transitions.length > 0

  async function run(transition, comments) {
    setBusy(true)
    setActionError('')
    setMessage('')
    try {
      const updated = await executeTransition(expense.id, transition.code, comments)
      setMessage(`${transition.name} done - now ${updated.state_name}.`)
      setReasonFor(null)
      setReason('')
      transitionsRequest.reload()
      historyRequest.reload()
      if (onChanged) onChanged(updated)
    } catch (err) {
      setActionError(err.message || 'The action could not be completed.')
    } finally {
      setBusy(false)
    }
  }

  function handleTransition(transition) {
    // A refusal deserves an explanation, so Reject collects one before it
    // runs. Everything else goes straight through.
    if (transition.to_state_code === 'REJECTED') {
      setReasonFor(transition)
      setActionError('')
      setMessage('')
      return
    }
    run(transition, null)
  }

  async function handleRemoveReceipt(attachment) {
    setBusy(true)
    setActionError('')
    try {
      await deleteReceipt(attachment.id)
      setMessage(`Removed ${attachment.file_name}.`)
      if (onChanged) onChanged({ ...expense })
    } catch (err) {
      setActionError(err.message || 'The receipt could not be removed.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <aside className="panel">
      <h2>{formatMoney(expense.amount, expense.currency)}</h2>

      <dl className="details">
        <dt>Employee</dt>
        <dd>{expense.employee.name}</dd>

        <dt>Business unit</dt>
        <dd>{expense.business_unit.name}</dd>

        <dt>Date</dt>
        <dd>{formatDate(expense.expense_date)}</dd>

        <dt>Category</dt>
        <dd>{expense.category.name}</dd>

        <dt>Merchant</dt>
        <dd>{expense.merchant ?? <span className="muted">Not given</span>}</dd>

        <dt>Receipt number</dt>
        <dd>
          {expense.reference_number ? (
            <code className="small">{expense.reference_number}</code>
          ) : (
            <span className="muted">Not given</span>
          )}
        </dd>

        <dt>Status</dt>
        <dd>
          <StateBadge
            code={expense.state_code}
            name={expense.state_name}
            isFinal={expense.is_final}
          />
        </dd>

        <dt>Description</dt>
        <dd>{expense.description}</dd>
      </dl>

      <h3 className="section-heading">Receipts</h3>
      {expense.attachments.length === 0 ? (
        <p className="muted small">No receipt attached.</p>
      ) : (
        <ul className="attachment-list">
          {expense.attachments.map((attachment) => (
            <li key={attachment.id} className="attachment">
              <button
                type="button"
                className="link-button"
                onClick={() => openReceipt(attachment.id)}
              >
                {attachment.file_name}
              </button>
              <span className="muted small">{formatFileSize(attachment.file_size)}</span>
              {editable && (
                <button
                  type="button"
                  className="button--secondary button--small"
                  disabled={busy}
                  onClick={() => handleRemoveReceipt(attachment)}
                >
                  Remove
                </button>
              )}
            </li>
          ))}
        </ul>
      )}

      <h3 className="section-heading">Available actions</h3>

      {transitionsRequest.loading && <Loading label="Checking..." />}
      <ErrorMessage
        message={transitionsRequest.error}
        onRetry={transitionsRequest.reload}
      />

      {!transitionsRequest.loading && transitions.length === 0 && (
        <p className="muted small">
          {expense.is_final
            ? 'This claim is settled. Nothing further can be done to it.'
            : 'You have no actions on this claim in its current state. Claims ' +
              'are submitted, cancelled and revised by the person who raised ' +
              'them, and approved or rejected by someone else.'}
        </p>
      )}

      {reasonFor ? (
        <div className="reason-box">
          <label htmlFor="reject_reason">Why is this being rejected?</label>
          <textarea
            id="reject_reason"
            rows={2}
            maxLength={1000}
            value={reason}
            placeholder="The claimant sees this on the claim's history."
            onChange={(e) => setReason(e.target.value)}
          />
          <div className="row-actions">
            <button
              type="button"
              className="button--danger button--small"
              disabled={busy || !reason.trim()}
              onClick={() => run(reasonFor, reason.trim())}
            >
              {busy ? 'Working...' : `Confirm ${reasonFor.name}`}
            </button>
            <button
              type="button"
              className="button--secondary button--small"
              disabled={busy}
              onClick={() => {
                setReasonFor(null)
                setReason('')
              }}
            >
              Back
            </button>
          </div>
        </div>
      ) : (
        <div className="row-actions">
          {onEdit && editable && (
            <button
              type="button"
              className="button--secondary button--small"
              disabled={busy}
              onClick={() => onEdit(expense)}
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
                // hardcoded action: anything landing in Rejected or Cancelled
                // reads as the destructive choice.
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
      )}

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

export default ExpenseDetail
