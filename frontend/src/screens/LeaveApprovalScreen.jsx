import { useEffect, useState } from 'react'
import LeaveRequestDetail from '../components/LeaveRequestDetail.jsx'
import LeaveRequestTable from '../components/LeaveRequestTable.jsx'
import { Empty, ErrorMessage, Loading } from '../components/StatusViews.jsx'
import { useAsync } from '../hooks/useAsync.js'
import { fetchLeaveRequests } from '../services/leaveService.js'

const PAGE_SIZE = 10

// Leave Approval: the queue of other people's requests waiting on a decision.
//
// Two rules are doing the work here, and neither is written in this file:
//
//   * which requests appear at all - the backend returns only requests inside
//     the caller's business-unit scope, so a manager at Branch 1 sees Branch 1
//     and its departments and nothing above or beside it,
//   * which buttons appear on one - the backend returns the transitions this
//     user may perform, which is how a manager's own pending request shows up
//     in the list with no Approve button on it.
//
// The screen is reached only by roles whose metadata grants the Leave Approval
// screen, but that is a convenience. Every endpoint it calls re-checks.
function LeaveApprovalScreen() {
  const [page, setPage] = useState(1)
  const [pendingOnly, setPendingOnly] = useState(true)
  const [selected, setSelected] = useState(null)

  const listRequest = useAsync(
    () => fetchLeaveRequests({ page, pageSize: PAGE_SIZE, pending: pendingOnly }),
    [page, pendingOnly],
  )

  const requests = listRequest.data?.items ?? []
  const total = listRequest.data?.total ?? 0
  const totalPages = listRequest.data?.total_pages ?? 1

  useEffect(() => {
    setSelected((current) =>
      requests.some((r) => r.id === current?.id) ? current : requests[0] ?? null,
    )
  }, [listRequest.data])

  function changeFilter(value) {
    setPendingOnly(value)
    setPage(1) // a new filter starts from the first page
  }

  function handleChanged(updated) {
    setSelected(updated)
    listRequest.reload()
  }

  const from = total === 0 ? 0 : (page - 1) * PAGE_SIZE + 1
  const to = Math.min(page * PAGE_SIZE, total)

  return (
    <>
      <header className="page-header">
        <h1>Leave Approval</h1>
        <p className="muted">
          Requests from people within your part of the organisation. Someone
          assigned a different business unit sees a different queue.
        </p>
      </header>

      <div className="toolbar">
        <select
          value={pendingOnly ? 'pending' : 'all'}
          aria-label="Filter requests"
          onChange={(event) => changeFilter(event.target.value === 'pending')}
        >
          <option value="pending">Awaiting a decision</option>
          <option value="all">All requests in my scope</option>
        </select>
      </div>

      {listRequest.loading && <Loading label="Loading requests..." />}
      <ErrorMessage message={listRequest.error} onRetry={listRequest.reload} />

      {!listRequest.loading && !listRequest.error && requests.length === 0 && (
        <Empty
          title={
            pendingOnly
              ? 'Nothing is waiting for a decision'
              : 'No leave requests in your scope'
          }
          hint={
            pendingOnly
              ? 'Switch the filter to see requests that have already been settled.'
              : 'Your business-unit assignment decides whose requests appear here.'
          }
        />
      )}

      {requests.length > 0 && (
        <div className="split">
          <div>
            <LeaveRequestTable
              requests={requests}
              selectedId={selected?.id}
              onSelect={setSelected}
              showEmployee
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
              onChanged={handleChanged}
            />
          )}
        </div>
      )}
    </>
  )
}

export default LeaveApprovalScreen
