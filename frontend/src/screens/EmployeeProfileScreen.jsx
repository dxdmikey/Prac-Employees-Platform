import { useEffect, useState } from 'react'
import EmployeeProfile from '../components/EmployeeProfile.jsx'
import { Empty, ErrorMessage, Loading } from '../components/StatusViews.jsx'
import { useAsync } from '../hooks/useAsync.js'
import { fetchEmployees } from '../services/employeeService.js'

// The Employee Profile screen.
//
// A profile needs somebody to show, and this screen has no row to arrive from,
// so it offers a picker of the employees the caller may see. The card itself
// is the same component the list screen uses - one profile layout, not two.
function EmployeeProfileScreen() {
  // A single page large enough to pick from without paging controls here.
  const request = useAsync(() => fetchEmployees({ page: 1, pageSize: 100 }), [])
  const employees = request.data?.items ?? []

  const [selectedId, setSelectedId] = useState('')

  useEffect(() => {
    if (employees.length > 0) {
      setSelectedId((current) =>
        employees.some((e) => String(e.id) === String(current))
          ? current
          : String(employees[0].id),
      )
    }
  }, [request.data])

  const selected = employees.find((e) => String(e.id) === String(selectedId))

  return (
    <>
      <header className="page-header">
        <h1>Employee Profile</h1>
        <p className="muted">Business details for one employee.</p>
      </header>

      {request.loading && <Loading label="Loading employees..." />}
      <ErrorMessage message={request.error} onRetry={request.reload} />

      {!request.loading && !request.error && employees.length === 0 && (
        <Empty
          title="No employees available"
          hint="Nobody in your organisational scope has an employee record."
        />
      )}

      {employees.length > 0 && (
        <>
          <div className="toolbar">
            <select
              value={selectedId}
              aria-label="Choose an employee"
              onChange={(event) => setSelectedId(event.target.value)}
            >
              {employees.map((employee) => (
                <option key={employee.id} value={employee.id}>
                  {employee.employee_code} - {employee.full_name}
                </option>
              ))}
            </select>
          </div>
          {selected && <EmployeeProfile employee={selected} />}
        </>
      )}
    </>
  )
}

export default EmployeeProfileScreen
