import { useEffect, useState } from 'react'
import LeaveRequestDetail from '../components/LeaveRequestDetail.jsx'
import LeaveRequestForm from '../components/LeaveRequestForm.jsx'
import LeaveRequestTable from '../components/LeaveRequestTable.jsx'
import { Empty, ErrorMessage, Loading } from '../components/StatusViews.jsx'
import { useAsync } from '../hooks/useAsync.js'
import {
  createLeaveRequest,
  fetchLeaveRequests,
  fetchLeaveTypes,
  updateLeaveRequest,
} from '../services/leaveService.js'

const PAGE_SIZE = 10

// Leave Requests: where an employee raises and works on their own requests.
//
// The screen offers a form and a list. What it does *not* offer is any
// judgement about which actions are allowed - Submit, Cancel, Approve and
// Reject all arrive from the backend through the detail panel. That is why
// this component works unchanged for a manager, who sees the same screen for
// their own leave and is offered exactly the same two actions on a draft.
function LeaveRequestsScreen() {
  const [page, setPage] = useState(1)
  const [selected, setSelected] = useState(null)
  const [mode, setMode] = useState('view') // view | create | edit
  const [notice, setNotice] = useState('')

  const listRequest = useAsync(
    () => fetchLeaveRequests({ page, pageSize: PAGE_SIZE, mine: true }),
    [page],
  )
  // Loaded once: the dropdown options rarely change and every form needs them.
  const typesRequest = useAsync(fetchLeaveTypes, [])

  const requests = listRequest.data?.items ?? []
  const total = listRequest.data?.total ?? 0
  const totalPages = listRequest.data?.total_pages ?? 1
  const leaveTypes = typesRequest.data ?? []

  useEffect(() => {
    setSelected((current) =>
      requests.some((r) => r.id === current?.id) ? current : requests[0] ?? null,
    )
  }, [listRequest.data])

  async function handleCreate(payload) {
    const created = await createLeaveRequest(payload)
    setNotice(
      `Draft saved for ${created.total_days} ${
        created.total_days === 1 ? 'day' : 'days'
      }. Submit it when you are ready.`,
    )
    setMode('view')
    listRequest.reload()
    setSelected(created)
  }

  async function handleUpdate(payload) {
    const updated = await updateLeaveRequest(selected.id, payload)
    setNotice(`Draft updated - now ${updated.total_days} days.`)
    setMode('view')
    listRequest.reload()
    setSelected(updated)
  }

  // After a transition the row in the table is stale, so both the list and the
  // selection are refreshed from the server rather than patched locally.
  function handleChanged(updated) {
    setSelected(updated)
    listRequest.reload()
  }

  const from = total === 0 ? 0 : (page - 1) * PAGE_SIZE + 1
  const to = Math.min(page * PAGE_SIZE, total)

  return (
    <>
      <header className="page-header">
        <h1>Leave Requests</h1>
        <p className="muted">
          Raise a request, edit it while it is still a draft, and submit it for
          approval.
        </p>
      </header>

      <div className="toolbar">
        <button
          type="button"
          className="button--small"
          disabled={mode === 'create'}
          onClick={() => {
            setMode('create')
            setNotice('')
          }}
        >
          New request
        </button>
      </div>

      {notice && (
        <div className="status status--success" role="status">
          {notice}
        </div>
      )}

      <ErrorMessage message={typesRequest.error} onRetry={typesRequest.reload} />

      {mode === 'create' && (
        <LeaveRequestForm
          leaveTypes={leaveTypes}
          onSubmit={handleCreate}
          onCancel={() => setMode('view')}
        />
      )}

      {mode === 'edit' && selected && (
        <LeaveRequestForm
          request={selected}
          leaveTypes={leaveTypes}
          onSubmit={handleUpdate}
          onCancel={() => setMode('view')}
        />
      )}

      {listRequest.loading && <Loading label="Loading your requests..." />}
      <ErrorMessage message={listRequest.error} onRetry={listRequest.reload} />

      {!listRequest.loading && !listRequest.error && requests.length === 0 && (
        <Empty
          title="No requests yet"
          hint="Use New request above to raise your first one."
        />
      )}

      {requests.length > 0 && (
        <div className="split">
          <div>
            <LeaveRequestTable
              requests={requests}
              selectedId={selected?.id}
              onSelect={(request) => {
                setSelected(request)
                setMode('view')
              }}
            />

            <div className="pagination">
              <span className="muted small">
                Showing {from}-{to} of {total}
              </span>
              <div className="row-actions">
                <button
                  type="button"
                  className="button--secondary button--small"
                  disabled={page <= 1 || listRequest.loading}
                  onClick={() => setPage((p) => p - 1)}
                >
                  Previous
                </button>
                <span className="muted small">
                  Page {page} of {totalPages}
                </span>
                <button
                  type="button"
                  className="button--secondary button--small"
                  disabled={page >= totalPages || listRequest.loading}
                  onClick={() => setPage((p) => p + 1)}
                >
                  Next
                </button>
              </div>
            </div>
          </div>

          {selected && mode !== 'edit' && (
            <LeaveRequestDetail
              key={selected.id}
              request={selected}
              onChanged={handleChanged}
              onEdit={() => {
                setMode('edit')
                setNotice('')
              }}
            />
          )}
        </div>
      )}
    </>
  )
}

export default LeaveRequestsScreen
