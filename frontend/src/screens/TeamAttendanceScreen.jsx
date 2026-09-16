import { useState } from 'react'
import AttendanceTable from '../components/AttendanceTable.jsx'
import { Empty, ErrorMessage, Loading } from '../components/StatusViews.jsx'
import { useAsync } from '../hooks/useAsync.js'
import {
  ATTENDANCE_STATUSES,
  fetchAttendance,
  statusLabel,
} from '../services/attendanceService.js'

const PAGE_SIZE = 15

// Team Attendance: everyone in the caller's part of the organisation.
//
// Which people appear is not decided here. The backend returns attendance for
// the caller's own record plus anyone inside their business-unit scope they
// hold APPROVE for, so a manager at Branch 1 sees Branch 1 and the departments
// beneath it, and nothing beside or above them. This screen only draws what
// comes back.
//
// The "Missing checkout" filter is the one a manager actually uses: it finds
// days where someone checked in and never checked out.
function TeamAttendanceScreen() {
  const [page, setPage] = useState(1)
  const [attendanceStatus, setAttendanceStatus] = useState('')
  const [openOnly, setOpenOnly] = useState(false)
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')

  const listRequest = useAsync(
    () =>
      fetchAttendance({
        page,
        pageSize: PAGE_SIZE,
        attendanceStatus,
        openOnly,
        dateFrom,
        dateTo,
      }),
    [page, attendanceStatus, openOnly, dateFrom, dateTo],
  )

  const records = listRequest.data?.items ?? []
  const total = listRequest.data?.total ?? 0
  const totalPages = listRequest.data?.total_pages ?? 1

  function changeFilter(setter, value) {
    setter(value)
    setPage(1) // a new filter starts from the first page
  }

  const from = total === 0 ? 0 : (page - 1) * PAGE_SIZE + 1
  const to = Math.min(page * PAGE_SIZE, total)

  return (
    <>
      <header className="page-header">
        <h1>Team Attendance</h1>
        <p className="muted">
          Attendance for people within your part of the organisation. Someone
          assigned a different business unit sees a different team.
        </p>
      </header>

      <div className="toolbar">
        <select
          value={attendanceStatus}
          aria-label="Filter by status"
          onChange={(e) => changeFilter(setAttendanceStatus, e.target.value)}
        >
          <option value="">All statuses</option>
          {ATTENDANCE_STATUSES.map((status) => (
            <option key={status} value={status}>
              {statusLabel(status)}
            </option>
          ))}
        </select>

        <label className="toolbar__check">
          <input
            type="checkbox"
            checked={openOnly}
            onChange={(e) => changeFilter(setOpenOnly, e.target.checked)}
          />
          Missing checkout only
        </label>

        <label className="toolbar__field">
          <span className="muted small">From</span>
          <input
            type="date"
            value={dateFrom}
            aria-label="From date"
            onChange={(e) => changeFilter(setDateFrom, e.target.value)}
          />
        </label>

        <label className="toolbar__field">
          <span className="muted small">To</span>
          <input
            type="date"
            value={dateTo}
            aria-label="To date"
            min={dateFrom || undefined}
            onChange={(e) => changeFilter(setDateTo, e.target.value)}
          />
        </label>
      </div>

      {listRequest.loading && <Loading label="Loading team attendance..." />}
      <ErrorMessage message={listRequest.error} onRetry={listRequest.reload} />

      {!listRequest.loading && !listRequest.error && records.length === 0 && (
        <Empty
          title="No attendance matches"
          hint="Try clearing the filters, or check your business-unit scope."
        />
      )}

      {records.length > 0 && (
        <>
          <AttendanceTable records={records} showEmployee />

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
        </>
      )}
    </>
  )
}

export default TeamAttendanceScreen
