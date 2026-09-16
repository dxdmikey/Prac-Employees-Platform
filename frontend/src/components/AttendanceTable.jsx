import {
  formatDate,
  formatDuration,
  formatTime,
  statusLabel,
} from '../services/attendanceService.js'

// A day's attendance status as a badge.
//
// The mapping is about what the status *means* to a reader, which is a
// presentation decision and belongs here: a finished day is settled, a missing
// checkout wants attention, an unplanned absence is a problem. The statuses
// themselves come from the backend.
function AttendanceBadge({ status }) {
  let modifier = 'badge--state-done'
  if (status === 'INCOMPLETE') modifier = 'badge--state-open'
  if (status === 'ABSENT') modifier = 'badge--state-rejected'
  if (status === 'ON_LEAVE' || status === 'HALF_DAY') modifier = 'badge--state-open'

  return <span className={`badge ${modifier}`}>{statusLabel(status)}</span>
}

// One table of attendance, used by both the employee and the manager screens.
//
// They differ in which records they ask the backend for, not in how a day
// looks, so there is one table rather than two. The employee column is
// optional because on My Attendance every row is the same person.
function AttendanceTable({ records, showEmployee = false, onSelect, selectedId }) {
  return (
    <div className="table-wrap">
      <table className="table">
        <thead>
          <tr>
            {showEmployee && <th>Employee</th>}
            <th>Date</th>
            <th>Check in</th>
            <th>Check out</th>
            <th>Worked</th>
            {showEmployee && <th>Business unit</th>}
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {records.map((record) => (
            <tr
              key={record.id}
              className={record.id === selectedId ? 'table__row--selected' : ''}
            >
              {showEmployee && (
                <td>
                  {onSelect ? (
                    <button
                      type="button"
                      className="link-button"
                      onClick={() => onSelect(record)}
                    >
                      {record.employee.name}
                    </button>
                  ) : (
                    record.employee.name
                  )}
                </td>
              )}
              <td className="small">{formatDate(record.attendance_date)}</td>
              <td className="small">{formatTime(record.check_in)}</td>
              <td className="small">{formatTime(record.check_out)}</td>
              <td className="small">{formatDuration(record.worked_minutes)}</td>
              {showEmployee && (
                <td className="small">{record.business_unit.name}</td>
              )}
              <td>
                <AttendanceBadge status={record.attendance_status} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export { AttendanceBadge }
export default AttendanceTable
