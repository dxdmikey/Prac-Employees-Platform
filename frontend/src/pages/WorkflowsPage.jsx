import { useState } from 'react'
import StateBadge from '../components/StateBadge.jsx'
import { Empty, ErrorMessage, Loading } from '../components/StatusViews.jsx'
import { useAsync } from '../hooks/useAsync.js'
import { fetchWorkflow, fetchWorkflows } from '../services/workflowService.js'

// The workflow admin screen: read the definition out of the database and show
// it. Nothing about the demo workflow is written here - the states, the arrows
// and the roles all arrive from /api/workflows/{code}.
function WorkflowsPage() {
  const listRequest = useAsync(fetchWorkflows, [])
  const [selectedCode, setSelectedCode] = useState(null)

  const workflows = listRequest.data ?? []
  const code = selectedCode ?? workflows[0]?.code ?? null

  const detailRequest = useAsync(
    () => (code ? fetchWorkflow(code) : Promise.resolve(null)),
    [code],
  )
  const detail = detailRequest.data

  // Group the arrows by the state they leave from, which is what turns a flat
  // list of transitions into something diagram-shaped.
  function transitionsFrom(stateCode) {
    return (detail?.transitions ?? []).filter((t) => t.from_state_code === stateCode)
  }

  return (
    <>
      <header className="page-header">
        <h1>Workflows</h1>
        <p className="muted">
          Every process is stored as states and transitions. One generic engine
          reads this metadata - there is no per-application workflow code.
        </p>
      </header>

      {listRequest.loading && <Loading label="Loading workflows..." />}
      <ErrorMessage message={listRequest.error} onRetry={listRequest.reload} />

      {!listRequest.loading && !listRequest.error && workflows.length === 0 && (
        <Empty
          title="No workflows defined"
          hint="Run python scripts/seed_metadata.py to load the demo workflow."
        />
      )}

      {workflows.length > 0 && (
        <div className="split">
          <section className="panel panel--flush">
            <ul className="tree">
              {workflows.map((workflow) => (
                <li key={workflow.code} className="tree__item">
                  <div
                    className={
                      workflow.code === code
                        ? 'tree__row tree__row--selected'
                        : 'tree__row'
                    }
                  >
                    <button
                      type="button"
                      className="tree__label"
                      onClick={() => setSelectedCode(workflow.code)}
                    >
                      <span className="tree__name">{workflow.name}</span>
                      {!workflow.is_active && (
                        <span className="badge badge--muted">Inactive</span>
                      )}
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          </section>

          <aside className="panel">
            {detailRequest.loading && <Loading label="Loading definition..." />}
            <ErrorMessage
              message={detailRequest.error}
              onRetry={detailRequest.reload}
            />

            {detail && (
              <>
                <h2>{detail.name}</h2>
                <p className="muted small">{detail.description}</p>

                <h3 className="section-heading">States</h3>
                <div className="badge-row">
                  {detail.states.map((state) => (
                    <StateBadge
                      key={state.code}
                      code={state.code}
                      name={state.name}
                      isFinal={state.is_final}
                    />
                  ))}
                </div>

                <h3 className="section-heading">Flow</h3>
                {/* A simple text diagram, generated from the metadata. */}
                <ul className="flow">
                  {detail.states.map((state) => {
                    const outgoing = transitionsFrom(state.code)
                    return (
                      <li key={state.code} className="flow__state">
                        <StateBadge
                          code={state.code}
                          name={state.name}
                          isFinal={state.is_final}
                        />
                        {state.is_initial && (
                          <span className="badge badge--muted">start</span>
                        )}
                        {outgoing.length === 0 ? (
                          state.is_final && (
                            <div className="flow__end muted small">
                              final &ndash; nothing leaves this state
                            </div>
                          )
                        ) : (
                          <ul className="flow__arrows">
                            {outgoing.map((transition) => (
                              <li key={transition.code} className="flow__arrow">
                                <span className="flow__action">
                                  {transition.name}
                                </span>
                                <span className="muted"> &rarr; </span>
                                <strong>{transition.to_state_name}</strong>
                                <div className="muted small">
                                  allowed to:{' '}
                                  {transition.allowed_role_codes.length
                                    ? transition.allowed_role_codes.join(', ')
                                    : 'nobody (not configured)'}
                                </div>
                              </li>
                            ))}
                          </ul>
                        )}
                      </li>
                    )
                  })}
                </ul>
              </>
            )}
          </aside>
        </div>
      )}
    </>
  )
}

export default WorkflowsPage
