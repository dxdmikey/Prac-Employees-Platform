import StateBadge from './StateBadge.jsx'
import { formatDate } from '../services/attendanceService.js'
import { formatMoney } from '../services/expenseService.js'

// One table of expense claims, used by both the employee and the approval
// screens. They differ in which claims they ask for, not in how one looks.
function ExpenseTable({ expenses, selectedId, onSelect, showEmployee = false }) {
  return (
    <div className="table-wrap">
      <table className="table">
        <thead>
          <tr>
            {showEmployee && <th>Employee</th>}
            <th>Date</th>
            <th>Category</th>
            <th>Merchant</th>
            {/* Money right-aligns, so the decimal points line up and a column
                of figures can be scanned down rather than read across. */}
            <th className="cell--number">Amount</th>
            <th>Description</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {expenses.map((expense) => (
            <tr
              key={expense.id}
              className={expense.id === selectedId ? 'table__row--selected' : ''}
            >
              {showEmployee && (
                <td>
                  <button
                    type="button"
                    className="link-button"
                    onClick={() => onSelect(expense)}
                  >
                    {expense.employee.name}
                  </button>
                </td>
              )}
              <td className="small">
                {showEmployee ? (
                  formatDate(expense.expense_date)
                ) : (
                  <button
                    type="button"
                    className="link-button"
                    onClick={() => onSelect(expense)}
                  >
                    {formatDate(expense.expense_date)}
                  </button>
                )}
              </td>
              <td className="small">{expense.category.name}</td>
              <td className="small">{expense.merchant ?? '-'}</td>
              <td className="small cell--number">
                {formatMoney(expense.amount, expense.currency)}
              </td>
              {/* Truncated by CSS, not cut here, so the full text stays
                  available to a screen reader and in the detail panel. */}
              <td className="small cell--clip" title={expense.description}>
                {expense.description}
              </td>
              <td>
                <StateBadge
                  code={expense.state_code}
                  name={expense.state_name}
                  isFinal={expense.is_final}
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default ExpenseTable
