import { useEffect, useState } from 'react'
import TimesheetDetail from '../components/TimesheetDetail.jsx'
import TimesheetForm from '../components/TimesheetForm.jsx'
import TimesheetTable from '../components/TimesheetTable.jsx'
import { Empty, ErrorMessage, Loading } from '../components/StatusViews.jsx'
import { useAsync } from '../hooks/useAsync.js'
import {
  createTimesheet,
  fetchTimesheetSummary,
  fetchTimesheets,
  formatHours,
  updateTimesheet,
} from '../services/timesheetService.js'

const PAGE_SIZE = 10

// Timesheet: where an employee records their own work and submits it.
//
// The screen offers a form and a list. What it does not offer is any judgement
// about which actions are allowed - Submit, Revise, Approve and Reject all
// arrive from the backend through the detail panel. That is why this component
// works unchanged for a manager looking at their own entries: they are offered
// exactly the same actions on a draft as anybody else.
function TimesheetScreen() {
  const [page, setPage] = useState(1)
  const [selected, setSelected] = useState(null)
  const [mode, setMode] = useState('view') // view | create | edit
  const [notice, setNotice] = useState('')

  const listRequest = useAsync(
    () => fetchTimesheets({ page, pageSize: PAGE_SIZE, mine: true }),
    [page],
  )
  const summaryRequest = useAsync(fetchTimesheetSummary, [])

  const entries = listRequest.data?.items ?? []
  const total = listRequest.data?.total ?? 0
  const totalPages = listRequest.data?.total_pages ?? 1
  const summary = summaryRequest.data

  useEffect(() => {
    setSelected((current) =>
      entries.some((e) => e.id === current?.id) ? current : entries[0] ?? null,
    )
  }, [listRequest.data])

  function refresh() {
    listRequest.reload()
    summaryRequest.reload()
  }

  async function handleCreate(payload) {
    const created = await createTimesheet(payload)
    setNotice(
      `Draft saved for ${formatHours(created.hours)}. Submit it when you are ready.`,
    )
    setMode('view')
    refresh()
    setSelected(created)
  }

  async function handleUpdate(payload) {
    const updated = await updateTimesheet(selected.id, payload)
    setNotice(`Draft updated - now ${formatHours(updated.hours)}.`)
    setMode('view')
    refresh()
    setSelected(updated)
  }

  function handleChanged(updated) {
    setSelected(updated)
    refresh()
  }

  const from = total === 0 ? 0 : (page - 1) * PAGE_SIZE + 1
  const to = Math.min(page * PAGE_SIZE, total)

  return (
    <>
      <header className="page-header">
        <h1>Timesheet</h1>
        <p className="muted">
          Record what you worked on, edit it while it is still a draft, and
          submit it for review.
        </p>
      </header>

      {summary && (
        <div className="summary-row">
          <div className="summary-tile">
            <div className="summary-tile__value">{summary.total_entries}</div>
            <div className="muted small">Entries</div>
          </div>
          <div className="summary-tile">
            <div className="summary-tile__value">{summary.draft}</div>
            <div className="muted small">Draft</div>
          </div>
          <div className="summary-tile">
            <div className="summary-tile__value">{summary.submitted}</div>
            <div className="muted small">Awaiting review</div>
          </div>
          <div className="summary-tile">
            <div className="summary-tile__value">{summary.approved_hours}</div>
            <div className="muted small">Approved hours</div>
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
          Record work
        </button>
      </div>

      {notice && (
        <div className="status status--success" role="status">
          {notice}
        </div>
      )}

      {mode === 'create' && (
        <TimesheetForm onSubmit={handleCreate} onCancel={() => setMode('view')} />
      )}

      {mode === 'edit' && selected && (
        <TimesheetForm
          timesheet={selected}
          onSubmit={handleUpdate}
          onCancel={() => setMode('view')}
        />
      )}

      {listRequest.loading && <Loading label="Loading your timesheets..." />}
      <ErrorMessage message={listRequest.error} onRetry={listRequest.reload} />

      {!listRequest.loading && !listRequest.error && entries.length === 0 && (
        <Empty
          title="No work recorded yet"
          hint="Use Record work above to add your first entry."
        />
      )}

      {entries.length > 0 && (
        <div className="split">
          <div>
            <TimesheetTable
              entries={entries}
              selectedId={selected?.id}
              onSelect={(entry) => {
                setSelected(entry)
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
            <TimesheetDetail
              key={selected.id}
              timesheet={selected}
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

export default TimesheetScreen
