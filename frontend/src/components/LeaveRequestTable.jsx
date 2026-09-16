import StateBadge from './StateBadge.jsx'
import { formatDate } from '../services/leaveService.js'

// One table of leave requests, used by all three leave screens.
//
// The three screens differ in *which* requests they ask the backend for, not
// in how a request looks, so there is one table rather than three. The
// employee column is optional because on "My Leave" every row is the same
// person and repeating their name 20 times tells the reader nothing.
function LeaveRequestTable({ requests, selectedId, onSelect, showEmployee = false }) {
  return (
    <div className="table-wrap">
      <table className="table">
        <thead>
          <tr>
            {showEmployee && <th>Employee</th>}
            <th>Type</th>
            <th>Dates</th>
            <th>Days</th>
            {showEmployee && <th>Business unit</th>}
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {requests.map((request) => (
            <tr
              key={request.id}
              className={request.id === selectedId ? 'table__row--selected' : ''}
            >
              {showEmployee && (
                <td>
                  <button
                    type="button"
                    className="link-button"
                    onClick={() => onSelect(request)}
                  >
                    {request.employee.name}
                  </button>
                </td>
              )}
              <td className={showEmployee ? 'small' : undefined}>
                {showEmployee ? (
                  request.leave_type.name
                ) : (
                  <button
                    type="button"
                    className="link-button"
                    onClick={() => onSelect(request)}
                  >
                    {request.leave_type.name}
                  </button>
                )}
              </td>
              <td className="small">
                {formatDate(request.start_date)} - {formatDate(request.end_date)}
              </td>
              <td className="small">{request.total_days}</td>
              {showEmployee && (
                <td className="small">{request.business_unit.name}</td>
              )}
              <td>
                <StateBadge
                  code={request.state_code}
                  name={request.state_name}
                  isFinal={request.is_final}
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default LeaveRequestTable
