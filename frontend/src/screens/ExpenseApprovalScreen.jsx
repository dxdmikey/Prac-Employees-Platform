import { useEffect, useState } from 'react'
import ExpenseDetail from '../components/ExpenseDetail.jsx'
import ExpenseTable from '../components/ExpenseTable.jsx'
import { Empty, ErrorMessage, Loading } from '../components/StatusViews.jsx'
import { useAsync } from '../hooks/useAsync.js'
import {
  fetchCategories,
  fetchExpenseSummary,
  fetchExpenses,
  formatMoney,
} from '../services/expenseService.js'

const PAGE_SIZE = 15

// Expense Approval: the queue of other people's claims waiting on a decision.
//
// Two rules do the work and neither is written in this file:
//
//   * which claims appear - the backend returns only claims inside the
//     caller's business-unit scope, so a manager at Branch 1 sees Branch 1 and
//     the departments beneath it and nothing above or beside them,
//   * which buttons appear on one - the backend returns the transitions this
//     user may perform, which is why a manager's own submitted claim shows up
//     in the list with no Approve button on it.
function ExpenseApprovalScreen() {
  const [page, setPage] = useState(1)
  const [pendingOnly, setPendingOnly] = useState(true)
  const [categoryId, setCategoryId] = useState('')
  const [selected, setSelected] = useState(null)

  const listRequest = useAsync(
    () =>
      fetchExpenses({
        page,
        pageSize: PAGE_SIZE,
        pending: pendingOnly,
        categoryId,
      }),
    [page, pendingOnly, categoryId],
  )
  const summaryRequest = useAsync(fetchExpenseSummary, [])
  const categoriesRequest = useAsync(fetchCategories, [])

  const expenses = listRequest.data?.items ?? []
  const total = listRequest.data?.total ?? 0
  const totalPages = listRequest.data?.total_pages ?? 1
  const summary = summaryRequest.data
  const categories = categoriesRequest.data ?? []

  useEffect(() => {
    setSelected((current) =>
      expenses.some((e) => e.id === current?.id) ? current : expenses[0] ?? null,
    )
  }, [listRequest.data])

  function changeFilter(setter, value) {
    setter(value)
    setPage(1) // a new filter starts from the first page
  }

  function handleChanged() {
    listRequest.reload()
    summaryRequest.reload()
  }

  const from = total === 0 ? 0 : (page - 1) * PAGE_SIZE + 1
  const to = Math.min(page * PAGE_SIZE, total)

  return (
    <>
      <header className="page-header">
        <h1>Expense Approval</h1>
        <p className="muted">
          Claims from people within your part of the organisation. Someone
          assigned a different business unit sees a different queue.
        </p>
      </header>

      {summary && (
        <div className="summary-row">
          <div className="summary-tile">
            <div className="summary-tile__value">{summary.submitted}</div>
            <div className="muted small">Awaiting a decision</div>
          </div>
          <div className="summary-tile">
            <div className="summary-tile__value">
              {formatMoney(summary.submitted_amount, summary.currency)}
            </div>
            <div className="muted small">Submitted value</div>
          </div>
          <div className="summary-tile">
            <div className="summary-tile__value">
              {formatMoney(summary.approved_amount, summary.currency)}
            </div>
            <div className="muted small">Approved value</div>
          </div>
          <div className="summary-tile">
            <div className="summary-tile__value">{summary.total_claims}</div>
            <div className="muted small">Claims in scope</div>
          </div>
        </div>
      )}

      <div className="toolbar">
        <select
          value={pendingOnly ? 'pending' : 'all'}
          aria-label="Filter claims"
          onChange={(e) => changeFilter(setPendingOnly, e.target.value === 'pending')}
        >
          <option value="pending">Awaiting a decision</option>
          <option value="all">All claims in my scope</option>
        </select>

        <select
          value={categoryId}
          aria-label="Filter by category"
          onChange={(e) => changeFilter(setCategoryId, e.target.value)}
        >
          <option value="">All categories</option>
          {categories.map((category) => (
            <option key={category.id} value={category.id}>
              {category.name}
            </option>
          ))}
        </select>
      </div>

      {listRequest.loading && <Loading label="Loading claims..." />}
      <ErrorMessage message={listRequest.error} onRetry={listRequest.reload} />

      {!listRequest.loading && !listRequest.error && expenses.length === 0 && (
        <Empty
          title={
            pendingOnly
              ? 'Nothing is waiting for a decision'
              : 'No expense claims in your scope'
          }
          hint={
            pendingOnly
              ? 'Switch the filter to see claims that have already been settled.'
              : 'Your business-unit assignment decides whose claims appear here.'
          }
        />
      )}

      {expenses.length > 0 && (
        <div className="split">
          <div>
            <ExpenseTable
              expenses={expenses}
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
            <ExpenseDetail
              key={selected.id}
              expense={selected}
              onChanged={handleChanged}
            />
          )}
        </div>
      )}
    </>
  )
}

export default ExpenseApprovalScreen
