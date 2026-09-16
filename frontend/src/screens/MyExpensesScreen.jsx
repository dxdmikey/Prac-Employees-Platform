import { useEffect, useState } from 'react'
import ExpenseDetail from '../components/ExpenseDetail.jsx'
import ExpenseForm from '../components/ExpenseForm.jsx'
import ExpenseTable from '../components/ExpenseTable.jsx'
import { Empty, ErrorMessage, Loading } from '../components/StatusViews.jsx'
import { useAsync } from '../hooks/useAsync.js'
import {
  createExpense,
  fetchCategories,
  fetchExpenseSummary,
  fetchExpenses,
  formatMoney,
  updateExpense,
  uploadReceipt,
} from '../services/expenseService.js'

const PAGE_SIZE = 10

// My Expenses: where an employee raises claims and follows them through.
//
// The screen offers a form and a list. What it does not offer is any judgement
// about which actions are allowed - Submit, Cancel, Revise, Approve and Reject
// all arrive from the backend through the detail panel. That is why this
// component works unchanged for a manager looking at their own claims.
function MyExpensesScreen() {
  const [page, setPage] = useState(1)
  const [selected, setSelected] = useState(null)
  const [mode, setMode] = useState('view') // view | create | edit
  const [notice, setNotice] = useState('')

  const listRequest = useAsync(
    () => fetchExpenses({ page, pageSize: PAGE_SIZE, mine: true }),
    [page],
  )
  const summaryRequest = useAsync(fetchExpenseSummary, [])
  // Loaded once: the dropdown options rarely change and every form needs them.
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

  function refresh() {
    listRequest.reload()
    summaryRequest.reload()
  }

  // The claim is saved first and the receipt attached to the claim that now
  // exists, because an attachment needs an expense id to belong to. A failed
  // upload therefore leaves a saved draft rather than losing the whole form.
  async function handleCreate(payload, receipt) {
    const created = await createExpense(payload)
    if (receipt) {
      try {
        await uploadReceipt(created.id, receipt)
      } catch (err) {
        setNotice(
          `Draft saved, but the receipt was not attached: ${err.message} ` +
            'You can add it from the claim.',
        )
        setMode('view')
        refresh()
        setSelected(created)
        return
      }
    }
    setNotice(
      `Draft saved for ${formatMoney(created.amount, created.currency)}. ` +
        'Submit it when you are ready.',
    )
    setMode('view')
    refresh()
    setSelected(created)
  }

  async function handleUpdate(payload, receipt) {
    const updated = await updateExpense(selected.id, payload)
    if (receipt) await uploadReceipt(updated.id, receipt)
    setNotice(`Draft updated - ${formatMoney(updated.amount, updated.currency)}.`)
    setMode('view')
    refresh()
    setSelected(updated)
  }

  // After a transition or an attachment change the row is stale, so both the
  // list and the selection are refreshed from the server rather than patched.
  function handleChanged() {
    refresh()
  }

  const from = total === 0 ? 0 : (page - 1) * PAGE_SIZE + 1
  const to = Math.min(page * PAGE_SIZE, total)

  return (
    <>
      <header className="page-header">
        <h1>My Expenses</h1>
        <p className="muted">
          Claim what you have spent, edit it while it is still a draft, and
          submit it for approval.
        </p>
      </header>

      {summary && (
        <div className="summary-row">
          <div className="summary-tile">
            <div className="summary-tile__value">
              {formatMoney(summary.total_amount, summary.currency)}
            </div>
            <div className="muted small">Claimed</div>
          </div>
          <div className="summary-tile">
            <div className="summary-tile__value">
              {formatMoney(summary.submitted_amount, summary.currency)}
            </div>
            <div className="muted small">Awaiting a decision</div>
          </div>
          <div className="summary-tile">
            <div className="summary-tile__value">
              {formatMoney(summary.approved_amount, summary.currency)}
            </div>
            <div className="muted small">Approved</div>
          </div>
          <div className="summary-tile">
            <div className="summary-tile__value">{summary.rejected}</div>
            <div className="muted small">Rejected</div>
          </div>
        </div>
      )}

      <div className="toolbar">
        <button
          type="button"
          className="button--small"
          disabled={mode === 'create'}
          onClick={() => {
            setMode('create')
            setNotice('')
          }}
        >
          New expense
        </button>
      </div>

      {notice && (
        <div className="status status--success" role="status">
          {notice}
        </div>
      )}

      <ErrorMessage
        message={categoriesRequest.error}
        onRetry={categoriesRequest.reload}
      />

      {mode === 'create' && (
        <ExpenseForm
          categories={categories}
          onSubmit={handleCreate}
          onCancel={() => setMode('view')}
          onAttach
        />
      )}

      {mode === 'edit' && selected && (
        <ExpenseForm
          expense={selected}
          categories={categories}
          onSubmit={handleUpdate}
          onCancel={() => setMode('view')}
          onAttach
        />
      )}

      {listRequest.loading && <Loading label="Loading your expenses..." />}
      <ErrorMessage message={listRequest.error} onRetry={listRequest.reload} />

      {!listRequest.loading && !listRequest.error && expenses.length === 0 && (
        <Empty
          title="No expenses yet"
          hint="Use New expense above to raise your first claim."
        />
      )}

      {expenses.length > 0 && (
        <div className="split">
          <div>
            <ExpenseTable
              expenses={expenses}
              selectedId={selected?.id}
              onSelect={(expense) => {
                setSelected(expense)
                setMode('view')
              }}
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

          {selected && mode !== 'edit' && (
            <ExpenseDetail
              key={selected.id}
              expense={selected}
              onChanged={handleChanged}
              onEdit={() => {
                setMode('edit')
                setNotice('')
              }}
            />
          )}
        </div>
      )}
    </>
  )
}

export default MyExpensesScreen
