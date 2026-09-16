import { useEffect, useState } from 'react'
import EmployeeForm from '../components/EmployeeForm.jsx'
import EmployeeProfile, { StatusBadge } from '../components/EmployeeProfile.jsx'
import { Empty, ErrorMessage, Loading } from '../components/StatusViews.jsx'
import { useAsync } from '../hooks/useAsync.js'
import {
  EMPLOYMENT_STATUSES,
  createEmployee,
  fetchEmployees,
  statusLabel,
  updateEmployee,
} from '../services/employeeService.js'
import { fetchMyBusinessUnits } from '../services/organizationService.js'

const PAGE_SIZE = 10

// The Employee List screen.
//
// Paging happens on the server: this component asks for one page at a time and
// never holds the whole table. The filter dropdown is built from the business
// units the backend says this user can see, so there is nothing in it they are
// not allowed to ask about.
function EmployeeListScreen() {
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState('')
  const [appliedSearch, setAppliedSearch] = useState('')
  const [businessUnitId, setBusinessUnitId] = useState('')
  const [employmentStatus, setEmploymentStatus] = useState('')
  const [selected, setSelected] = useState(null)
  const [mode, setMode] = useState('view') // view | create | edit
  const [notice, setNotice] = useState('')

  const listRequest = useAsync(
    () =>
      fetchEmployees({
        page,
        pageSize: PAGE_SIZE,
        search: appliedSearch,
        businessUnitId,
        employmentStatus,
      }),
    [page, appliedSearch, businessUnitId, employmentStatus],
  )

  const scopeRequest = useAsync(fetchMyBusinessUnits, [])
  const businessUnits = scopeRequest.data?.visible ?? []

  // Candidates for the Manager dropdown: everyone active in scope, not just
  // the current page of the table. Loaded only while a form is open.
  const formOpen = mode !== 'view'
  const managersRequest = useAsync(
    () =>
      formOpen
        ? fetchEmployees({ page: 1, pageSize: 100, employmentStatus: 'ACTIVE' })
        : Promise.resolve(null),
    [formOpen],
  )
  const managerOptions = managersRequest.data?.items ?? []

  const employees = listRequest.data?.items ?? []
  const total = listRequest.data?.total ?? 0
  const totalPages = listRequest.data?.total_pages ?? 1

  // Keep a valid selection as the page changes.
  useEffect(() => {
    setSelected((current) =>
      employees.some((e) => e.id === current?.id) ? current : employees[0] ?? null,
    )
  }, [listRequest.data])

  function applySearch(event) {
    event.preventDefault()
    setPage(1)
    setAppliedSearch(search)
  }

  function changeFilter(setter, value) {
    setter(value)
    setPage(1) // a new filter starts from the first page
  }

  async function handleCreate(payload) {
    const created = await createEmployee(payload)
    setNotice(`Created ${created.full_name}.`)
    setMode('view')
    listRequest.reload()
    setSelected(created)
  }

  async function handleUpdate(payload) {
    const updated = await updateEmployee(selected.id, payload)
    setNotice(`Saved ${updated.full_name}.`)
    setMode('view')
    listRequest.reload()
    setSelected(updated)
  }

  const from = total === 0 ? 0 : (page - 1) * PAGE_SIZE + 1
  const to = Math.min(page * PAGE_SIZE, total)

  return (
    <>
      <header className="page-header">
        <h1>Employee List</h1>
        <p className="muted">
          Employees within your organisational scope. Someone assigned a
          different business unit sees a different list.
        </p>
      </header>

      <div className="toolbar">
        <form className="toolbar__search" onSubmit={applySearch}>
          <input
            type="search"
            value={search}
            placeholder="Search name, code, email or job title"
            aria-label="Search employees"
            onChange={(event) => setSearch(event.target.value)}
          />
          <button type="submit" className="button--small">
            Search
          </button>
        </form>

        <select
          value={businessUnitId}
          aria-label="Filter by business unit"
          onChange={(event) => changeFilter(setBusinessUnitId, event.target.value)}
        >
          <option value="">All business units</option>
          {businessUnits.map((unit) => (
            <option key={unit.id} value={unit.id}>
              {unit.name}
            </option>
          ))}
        </select>

        <select
          value={employmentStatus}
          aria-label="Filter by status"
          onChange={(event) => changeFilter(setEmploymentStatus, event.target.value)}
        >
          <option value="">All statuses</option>
          {EMPLOYMENT_STATUSES.map((status) => (
            <option key={status} value={status}>
              {statusLabel(status)}
            </option>
          ))}
        </select>

        <button
          type="button"
          className="button--small"
          onClick={() => {
            setMode('create')
            setNotice('')
          }}
        >
          Add employee
        </button>
      </div>

      {notice && (
        <div className="status status--success" role="status">
          {notice}
        </div>
      )}

      {listRequest.loading && <Loading label="Loading employees..." />}
      <ErrorMessage message={listRequest.error} onRetry={listRequest.reload} />

      {!listRequest.loading && !listRequest.error && employees.length === 0 && (
        <Empty
          title="No employees match"
          hint="Try clearing the search or filters, or check your business-unit scope."
        />
      )}

      {mode === 'create' && (
        <EmployeeForm
          businessUnits={businessUnits}
          managers={managerOptions}
          onSubmit={handleCreate}
          onCancel={() => setMode('view')}
        />
      )}

      {mode === 'edit' && selected && (
        <EmployeeForm
          employee={selected}
          businessUnits={businessUnits}
          managers={managerOptions}
          onSubmit={handleUpdate}
          onCancel={() => setMode('view')}
        />
      )}

      {employees.length > 0 && (
        <div className="split">
          <div>
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Code</th>
                    <th>Name</th>
                    <th>Job title</th>
                    <th>Business unit</th>
                    <th>Manager</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {employees.map((employee) => (
                    <tr
                      key={employee.id}
                      className={
                        employee.id === selected?.id ? 'table__row--selected' : ''
                      }
                    >
                      <td>
                        <code className="small">{employee.employee_code}</code>
                      </td>
                      <td>
                        <button
                          type="button"
                          className="link-button"
                          onClick={() => {
                            setSelected(employee)
                            setMode('view')
                          }}
                        >
                          {employee.full_name}
                        </button>
                      </td>
                      <td className="small">{employee.job_title ?? '-'}</td>
                      <td className="small">{employee.business_unit.name}</td>
                      <td className="small">{employee.manager?.name ?? '-'}</td>
                      <td>
                        <StatusBadge status={employee.employment_status} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

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

          {selected && mode === 'view' && (
            <EmployeeProfile employee={selected} onEdit={() => setMode('edit')} />
          )}
        </div>
      )}
    </>
  )
}

export default EmployeeListScreen
