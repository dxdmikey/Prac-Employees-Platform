import { useState } from 'react'
import AttendanceTable, { AttendanceBadge } from '../components/AttendanceTable.jsx'
import { Empty, ErrorMessage, Loading } from '../components/StatusViews.jsx'
import { useAsync } from '../hooks/useAsync.js'
import {
  checkIn,
  checkOut,
  fetchMyHistory,
  fetchToday,
  formatDate,
  formatDuration,
  formatTime,
} from '../services/attendanceService.js'

const HISTORY_DAYS = 30

// My Attendance: today at the top, history below.
//
// The two buttons are the interesting part. Whether each is shown comes from
// `can_check_in` / `can_check_out` in the backend's response, not from this
// component inspecting timestamps. That matters because the backend is what
// refuses a duplicate check-in, and a button that disagrees with the rule
// behind it is worse than no button at all.
function MyAttendanceScreen() {
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState('')
  const [actionError, setActionError] = useState('')

  const todayRequest = useAsync(fetchToday, [])
  const historyRequest = useAsync(() => fetchMyHistory(HISTORY_DAYS), [])

  const today = todayRequest.data
  const record = today?.attendance ?? null
  const history = historyRequest.data ?? []

  async function run(action, successMessage) {
    setBusy(true)
    setActionError('')
    setNotice('')
    try {
      const updated = await action()
      setNotice(successMessage(updated))
      todayRequest.reload()
      historyRequest.reload()
    } catch (err) {
      // A refused action is a normal outcome, not a crash - "you have already
      // checked in today" is the backend explaining a rule, and it is shown
      // exactly as written.
      setActionError(err.message || 'That could not be recorded.')
    } finally {
      // Always, so a button can never stay stuck on "Working...".
      setBusy(false)
    }
  }

  return (
    <>
      <header className="page-header">
        <h1>My Attendance</h1>
        <p className="muted">
          Your own working days. Check in when you start and check out when you
          finish; the worked time is calculated from the two.
        </p>
      </header>

      {todayRequest.loading && <Loading label="Loading today..." />}
      <ErrorMessage message={todayRequest.error} onRetry={todayRequest.reload} />

      {today && (
        <section className="panel">
          <div className="today__header">
            <div>
              <h2>{formatDate(today.attendance_date)}</h2>
              <p className="muted small">Today</p>
            </div>
            {record && (
              <AttendanceBadge status={record.attendance_status} />
            )}
          </div>

          <div className="summary-row">
            <div className="summary-tile">
              <div className="summary-tile__value">
                {formatTime(record?.check_in)}
              </div>
              <div className="muted small">Checked in</div>
            </div>
            <div className="summary-tile">
              <div className="summary-tile__value">
                {formatTime(record?.check_out)}
              </div>
              <div className="muted small">Checked out</div>
            </div>
            <div className="summary-tile">
              <div className="summary-tile__value">
                {formatDuration(record?.worked_minutes)}
              </div>
              <div className="muted small">Worked today</div>
            </div>
          </div>

          <div className="row-actions">
            {today.can_check_in && (
              <button
                type="button"
                disabled={busy}
                onClick={() =>
                  run(checkIn, (r) => `Checked in at ${formatTime(r.check_in)}.`)
                }
              >
                {busy && <span className="spinner" aria-hidden="true" />}
                {busy ? 'Working...' : 'Check In'}
              </button>
            )}
            {today.can_check_out && (
              <button
                type="button"
                disabled={busy}
                onClick={() =>
                  run(
                    checkOut,
                    (r) =>
                      `Checked out at ${formatTime(r.check_out)} - ` +
                      `${formatDuration(r.worked_minutes)} worked.`,
                  )
                }
              >
                {busy && <span className="spinner" aria-hidden="true" />}
                {busy ? 'Working...' : 'Check Out'}
              </button>
            )}
            {!today.can_check_in && !today.can_check_out && (
              <p className="muted small">
                {record
                  ? 'Your day is recorded. Nothing further to do today.'
                  : 'Attendance cannot be recorded for your account. Ask an ' +
                    'administrator to link it to an employee record.'}
              </p>
            )}
          </div>

          {notice && (
            <div className="status status--success" role="status">
              {notice}
            </div>
          )}
          <ErrorMessage message={actionError} />
        </section>
      )}

      <h2 className="section-heading">Last {HISTORY_DAYS} days</h2>

      {historyRequest.loading && <Loading label="Loading history..." />}
      <ErrorMessage message={historyRequest.error} onRetry={historyRequest.reload} />

      {!historyRequest.loading && !historyRequest.error && history.length === 0 && (
        <Empty
          title="No attendance recorded yet"
          hint="Your days will appear here once you start checking in."
        />
      )}

      {history.length > 0 && <AttendanceTable records={history} />}
    </>
  )
}

export default MyAttendanceScreen
