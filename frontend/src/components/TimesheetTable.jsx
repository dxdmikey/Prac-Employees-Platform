import StateBadge from './StateBadge.jsx'
import { formatDate } from '../services/attendanceService.js'
import { formatHours } from '../services/timesheetService.js'

// One table of timesheet entries, used by both the employee and the approval
// screens. They differ in which entries they ask for, not in how one looks.
function TimesheetTable({ entries, selectedId, onSelect, showEmployee = false }) {
  return (
    <div className="table-wrap">
      <table className="table">
        <thead>
          <tr>
            {showEmployee && <th>Employee</th>}
            <th>Date</th>
            <th>Hours</th>
            <th>Work</th>
            <th>Reference</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {entries.map((entry) => (
            <tr
              key={entry.id}
              className={entry.id === selectedId ? 'table__row--selected' : ''}
            >
              {showEmployee && (
                <td>
                  <button
                    type="button"
                    className="link-button"
                    onClick={() => onSelect(entry)}
                  >
                    {entry.employee.name}
                  </button>
                </td>
              )}
              <td className="small">
                {showEmployee ? (
                  formatDate(entry.work_date)
                ) : (
                  <button
                    type="button"
                    className="link-button"
                    onClick={() => onSelect(entry)}
                  >
                    {formatDate(entry.work_date)}
                  </button>
                )}
              </td>
              <td className="small">{formatHours(entry.hours)}</td>
              {/* Long descriptions are truncated by CSS rather than cut here,
                  so the full text stays available to a screen reader and in
                  the detail panel. */}
              <td className="small cell--clip" title={entry.work_description}>
                {entry.work_description}
              </td>
              <td className="small">
                {entry.reference ? (
                  <code className="small">{entry.reference}</code>
                ) : (
                  '-'
                )}
              </td>
              <td>
                <StateBadge
                  code={entry.state_code}
                  name={entry.state_name}
                  isFinal={entry.is_final}
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default TimesheetTable
