import { useEffect, useState } from 'react'
import TimesheetDetail from '../components/TimesheetDetail.jsx'
import TimesheetTable from '../components/TimesheetTable.jsx'
import { Empty, ErrorMessage, Loading } from '../components/StatusViews.jsx'
import { useAsync } from '../hooks/useAsync.js'
import { fetchTimesheets } from '../services/timesheetService.js'

const PAGE_SIZE = 15

// Timesheet Approval: the queue of other people's work waiting on a decision.
//
// Two rules do the work here and neither is written in this file:
//
//   * which entries appear - the backend returns only entries inside the
//     caller's business-unit scope, so a manager at Branch 1 sees Branch 1 and
//     its departments and nothing above or beside it,
//   * which buttons appear on one - the backend returns the transitions this
//     user may perform, which is why a manager's own submitted entry shows up
//     in the list with no Approve button on it.
function TimesheetApprovalScreen() {
  const [page, setPage] = useState(1)
  const [pendingOnly, setPendingOnly] = useState(true)
  const [selected, setSelected] = useState(null)

  const listRequest = useAsync(
    () => fetchTimesheets({ page, pageSize: PAGE_SIZE, pending: pendingOnly }),
    [page, pendingOnly],
  )

  const entries = listRequest.data?.items ?? []
  const total = listRequest.data?.total ?? 0
  const totalPages = listRequest.data?.total_pages ?? 1

  useEffect(() => {
    setSelected((current) =>
      entries.some((e) => e.id === current?.id) ? current : entries[0] ?? null,
    )
  }, [listRequest.data])

  function changeFilter(value) {
    setPendingOnly(value)
    setPage(1)
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
        <h1>Timesheet Approval</h1>
        <p className="muted">
          Recorded work from people within your part of the organisation.
          Someone assigned a different business unit sees a different queue.
        </p>
      </header>

      <div className="toolbar">
        <select
          value={pendingOnly ? 'pending' : 'all'}
          aria-label="Filter entries"
          onChange={(e) => changeFilter(e.target.value === 'pending')}
        >
          <option value="pending">Awaiting a decision</option>
          <option value="all">All entries in my scope</option>
        </select>
      </div>

      {listRequest.loading && <Loading label="Loading timesheets..." />}
      <ErrorMessage message={listRequest.error} onRetry={listRequest.reload} />

      {!listRequest.loading && !listRequest.error && entries.length === 0 && (
        <Empty
          title={
            pendingOnly
              ? 'Nothing is waiting for a decision'
              : 'No timesheets in your scope'
          }
          hint={
            pendingOnly
              ? 'Switch the filter to see entries that have already been settled.'
              : 'Your business-unit assignment decides whose work appears here.'
          }
        />
      )}

      {entries.length > 0 && (
        <div className="split">
          <div>
            <TimesheetTable
              entries={entries}
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
            <TimesheetDetail
              key={selected.id}
              timesheet={selected}
              onChanged={handleChanged}
            />
          )}
        </div>
      )}
    </>
  )
}

export default TimesheetApprovalScreen
