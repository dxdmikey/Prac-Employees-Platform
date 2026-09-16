import { useEffect, useState } from 'react'
import LeaveRequestDetail from '../components/LeaveRequestDetail.jsx'
import LeaveRequestTable from '../components/LeaveRequestTable.jsx'
import { Empty, ErrorMessage, Loading } from '../components/StatusViews.jsx'
import { useAsync } from '../hooks/useAsync.js'
import { fetchLeaveRequests, fetchLeaveSummary } from '../services/leaveService.js'

const PAGE_SIZE = 10

// My Leave: an employee's own record of time off.
//
// This screen only reads. Creating, editing and submitting live on Leave
// Requests, and approving lives on Leave Approval - so this one stays a calm
// overview of "where does my leave stand". The detail panel still shows the
// full history, because "who approved this, and when" is exactly the question
// people bring to this screen.
//
// It asks for mine=true, but that flag is a convenience rather than a
// protection: without it the backend would still only return requests this
// user is allowed to see.
function MyLeaveScreen() {
  const [page, setPage] = useState(1)
  const [selected, setSelected] = useState(null)

  const listRequest = useAsync(
    () => fetchLeaveRequests({ page, pageSize: PAGE_SIZE, mine: true }),
    [page],
  )
  const summaryRequest = useAsync(fetchLeaveSummary, [])

  const requests = listRequest.data?.items ?? []
  const total = listRequest.data?.total ?? 0
  const totalPages = listRequest.data?.total_pages ?? 1
  const summary = summaryRequest.data

  // Keep a valid selection as the page changes.
  useEffect(() => {
    setSelected((current) =>
      requests.some((r) => r.id === current?.id) ? current : requests[0] ?? null,
    )
  }, [listRequest.data])

  const from = total === 0 ? 0 : (page - 1) * PAGE_SIZE + 1
  const to = Math.min(page * PAGE_SIZE, total)

  return (
    <>
      <header className="page-header">
        <h1>My Leave</h1>
        <p className="muted">
          Every leave request you have raised, and where each one has got to.
        </p>
      </header>

      {summary && (
        <div className="summary-row">
          <div className="summary-tile">
            <div className="summary-tile__value">{summary.total_requests}</div>
            <div className="muted small">Requests</div>
          </div>
          <div className="summary-tile">
            <div className="summary-tile__value">{summary.pending}</div>
            <div className="muted small">Awaiting a decision</div>
          </div>
          <div className="summary-tile">
            <div className="summary-tile__value">{summary.approved}</div>
            <div className="muted small">Approved</div>
          </div>
          <div className="summary-tile">
            <div className="summary-tile__value">{summary.total_days_requested}</div>
            <div className="muted small">Days requested</div>
          </div>
        </div>
      )}

      {listRequest.loading && <Loading label="Loading your leave..." />}
      <ErrorMessage message={listRequest.error} onRetry={listRequest.reload} />

      {!listRequest.loading && !listRequest.error && requests.length === 0 && (
        <Empty
          title="You have no leave requests yet"
          hint="Raise one on the Leave Requests screen."
        />
      )}

      {requests.length > 0 && (
        <div className="split">
          <div>
            <LeaveRequestTable
              requests={requests}
              selectedId={selected?.id}
              onSelect={setSelected}
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

          {selected && (
            <LeaveRequestDetail
              key={selected.id}
              request={selected}
              showActions={false}
            />
          )}
        </div>
      )}
    </>
  )
}

export default MyLeaveScreen
