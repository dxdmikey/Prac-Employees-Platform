import { useState } from 'react'
import BusinessUnitTree from '../components/BusinessUnitTree.jsx'
import { Empty, ErrorMessage, Loading } from '../components/StatusViews.jsx'
import { useAsync } from '../hooks/useAsync.js'
import { fetchBusinessUnitTree } from '../services/organizationService.js'

// The organisation hierarchy, loaded from the backend.
//
// The nodes are not written anywhere in React - add a business unit to the
// database and it appears here. Selecting a node shows what an assignment to
// it would grant, which makes the inheritance rule visible.
function OrganizationPage() {
  const { data: tree, error, loading, reload } = useAsync(fetchBusinessUnitTree, [])
  const [selected, setSelected] = useState(null)

  // Count everything at or beneath a node - the same subtree the backend
  // would grant to somebody assigned there.
  function countSubtree(node) {
    return 1 + node.children.reduce((total, child) => total + countSubtree(child), 0)
  }

  return (
    <>
      <header className="page-header">
        <h1>Organisation</h1>
        <p className="muted">
          One self-referencing table holds every level. Assigning someone a
          business unit grants that unit and everything beneath it - never
          anything above it.
        </p>
      </header>

      {loading && <Loading label="Loading the organisation..." />}
      <ErrorMessage message={error} onRetry={reload} />

      {!loading && !error && tree && tree.length === 0 && (
        <Empty
          title="No business units yet"
          hint="Run python scripts/seed_metadata.py to load the development organisation."
        />
      )}

      {!loading && !error && tree && tree.length > 0 && (
        <div className="split">
          <section className="panel panel--flush">
            <BusinessUnitTree
              nodes={tree}
              selectedId={selected?.id}
              onSelect={setSelected}
            />
          </section>

          <aside className="panel">
            {selected ? (
              <>
                <h2>{selected.name}</h2>
                <dl className="details">
                  <dt>Type</dt>
                  <dd>{selected.business_unit_type_name}</dd>
                  <dt>Code</dt>
                  <dd>
                    <code>{selected.code}</code>
                  </dd>
                  <dt>Parent</dt>
                  <dd>{selected.parent_id === null ? 'None (root)' : selected.parent_id}</dd>
                  <dt>Status</dt>
                  <dd>{selected.is_active ? 'Active' : 'Inactive'}</dd>
                </dl>
                <p className="note small">
                  Someone assigned to {selected.name} can see{' '}
                  <strong>{countSubtree(selected)}</strong> business unit
                  {countSubtree(selected) === 1 ? '' : 's'}: this one
                  {selected.children.length > 0
                    ? ' and everything beneath it.'
                    : ' only, because nothing sits below it.'}
                </p>
              </>
            ) : (
              <>
                <h2>Select a business unit</h2>
                <p className="muted small">
                  Choose a node on the left to see its details and how much of
                  the organisation an assignment to it would grant.
                </p>
              </>
            )}
          </aside>
        </div>
      )}
    </>
  )
}

export default OrganizationPage
