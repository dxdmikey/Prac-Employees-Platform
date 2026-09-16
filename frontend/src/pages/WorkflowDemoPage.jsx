import { useEffect, useState } from 'react'
import StateBadge from '../components/StateBadge.jsx'
import { Empty, ErrorMessage, Loading } from '../components/StatusViews.jsx'
import { useAsync } from '../hooks/useAsync.js'
import {
  createDemoRequest,
  executeTransition,
  fetchAvailableTransitions,
  fetchDemoRequests,
  fetchHistory,
} from '../services/workflowService.js'

// The workflow demonstration screen.
//
// The important detail: the action buttons are not chosen here. The backend
// returns which transitions this user may perform on this record right now,
// and each one becomes a button. An employee sees Submit; a manager sees
// Approve and Reject - from the same component, with no role check in sight.
function WorkflowDemoPage() {
  const listRequest = useAsync(fetchDemoRequests, [])
  const requests = listRequest.data ?? []

  const [selectedId, setSelectedId] = useState(null)
  const [title, setTitle] = useState('')
  const [creating, setCreating] = useState(false)
  const [actionBusy, setActionBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [actionError, setActionError] = useState('')

  // Keep a valid selection as the list changes.
  useEffect(() => {
    if (requests.length > 0) {
      setSelectedId((current) =>
        requests.some((r) => r.id === current) ? current : requests[0].id,
      )
    } else {
      setSelectedId(null)
    }
  }, [requests])

  const selected = requests.find((r) => r.id === selectedId) ?? null

  const transitionsRequest = useAsync(
    () => (selectedId ? fetchAvailableTransitions(selectedId) : Promise.resolve([])),
    [selectedId],
  )
  const historyRequest = useAsync(
    () => (selectedId ? fetchHistory(selectedId) : Promise.resolve([])),
    [selectedId],
  )

  function refreshAll() {
    listRequest.reload()
    transitionsRequest.reload()
    historyRequest.reload()
  }

  async function handleCreate(event) {
    event.preventDefault()
    setCreating(true)
    setActionError('')
    setMessage('')
    try {
      const created = await createDemoRequest(title, null)
      setTitle('')
      setMessage(`Created "${created.title}".`)
      listRequest.reload()
      setSelectedId(created.id)
    } catch (err) {
      setActionError(err.message || 'The request could not be created.')
    } finally {
      // Always - so the button can never stay stuck.
      setCreating(false)
    }
  }

  async function handleTransition(transition) {
    setActionBusy(true)
    setActionError('')
    setMessage('')
    try {
      const updated = await executeTransition(selected.id, transition.code, null)
      setMessage(`${transition.name} done - now ${updated.current_state_name}.`)
      refreshAll()
    } catch (err) {
      // A refused transition is a normal outcome, not a crash: the backend
      // explains which rule said no.
      setActionError(err.message || 'The action could not be completed.')
    } finally {
      setActionBusy(false)
    }
  }

  const transitions = transitionsRequest.data ?? []
  const history = historyRequest.data ?? []

  return (
    <>
      <header className="page-header">
        <h1>Workflow demo</h1>
        <p className="muted">
          A throwaway record driven by the generic engine. The available actions
          come from the backend, based on the current state and your roles.
        </p>
      </header>

      <form className="panel inline-form" onSubmit={handleCreate}>
        <div className="inline-form__field">
          <label htmlFor="title">New request</label>
          <input
            id="title"
            type="text"
            value={title}
            placeholder="e.g. Laptop Purchase"
            onChange={(event) => setTitle(event.target.value)}
            required
          />
        </div>
        <button type="submit" disabled={creating || !title.trim()}>
          {creating && <span className="spinner" aria-hidden="true" />}
          {creating ? 'Creating...' : 'Create'}
        </button>
      </form>

      {message && (
        <div className="status status--success" role="status">
          {message}
        </div>
      )}
      <ErrorMessage message={actionError} />

      {listRequest.loading && <Loading label="Loading requests..." />}
      <ErrorMessage message={listRequest.error} onRetry={listRequest.reload} />

      {!listRequest.loading && !listRequest.error && requests.length === 0 && (
        <Empty
          title="No requests yet"
          hint="Create one above to watch it move through the workflow."
        />
      )}

      {requests.length > 0 && (
        <div className="split">
          <section className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Request</th>
                  <th>State</th>
                </tr>
              </thead>
              <tbody>
                {requests.map((request) => (
                  <tr
                    key={request.id}
                    className={request.id === selectedId ? 'table__row--selected' : ''}
                  >
                    <td>
                      <button
                        type="button"
                        className="link-button"
                        onClick={() => setSelectedId(request.id)}
                      >
                        {request.title}
                      </button>
                      <div className="muted small">
                        by {request.created_by_username}
                      </div>
                    </td>
                    <td>
                      <StateBadge
                        code={request.current_state_code}
                        name={request.current_state_name}
                        isFinal={request.is_final}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>

          <aside className="panel">
            {selected && (
              <>
                <h2>{selected.title}</h2>
                <dl className="details">
                  <dt>Current state</dt>
                  <dd>
                    <StateBadge
                      code={selected.current_state_code}
                      name={selected.current_state_name}
                      isFinal={selected.is_final}
                    />
                  </dd>
                  <dt>Raised by</dt>
                  <dd>{selected.created_by_username}</dd>
                </dl>

                <h3 className="section-heading">Available actions</h3>
                {transitionsRequest.loading && <Loading label="Checking..." />}
                {!transitionsRequest.loading && transitions.length === 0 && (
                  <p className="muted small">
                    {selected.is_final
                      ? 'This request is finished.'
                      : 'You have no actions on this request in its current state.'}
                  </p>
                )}
                <div className="row-actions">
                  {transitions.map((transition) => (
                    <button
                      key={transition.code}
                      type="button"
                      className={
                        transition.to_state_code === 'REJECTED'
                          ? 'button--danger button--small'
                          : 'button--small'
                      }
                      disabled={actionBusy}
                      onClick={() => handleTransition(transition)}
                    >
                      {actionBusy ? 'Working...' : transition.name}
                    </button>
                  ))}
                </div>

                <h3 className="section-heading">History</h3>
                {historyRequest.loading && <Loading label="Loading history..." />}
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
              </>
            )}
          </aside>
        </div>
      )}
    </>
  )
}

export default WorkflowDemoPage
