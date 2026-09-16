import DashboardView from './DashboardView.jsx'
import EmployeeListScreen from '../screens/EmployeeListScreen.jsx'
import EmployeeProfileScreen from '../screens/EmployeeProfileScreen.jsx'
import ExpenseApprovalScreen from '../screens/ExpenseApprovalScreen.jsx'
import LeaveApprovalScreen from '../screens/LeaveApprovalScreen.jsx'
import LeaveRequestsScreen from '../screens/LeaveRequestsScreen.jsx'
import MyAttendanceScreen from '../screens/MyAttendanceScreen.jsx'
import MyExpensesScreen from '../screens/MyExpensesScreen.jsx'
import MyLeaveScreen from '../screens/MyLeaveScreen.jsx'
import TeamAttendanceScreen from '../screens/TeamAttendanceScreen.jsx'
import TimesheetApprovalScreen from '../screens/TimesheetApprovalScreen.jsx'
import TimesheetScreen from '../screens/TimesheetScreen.jsx'
import { Empty, ErrorMessage, Loading } from './StatusViews.jsx'
import { useAsync } from '../hooks/useAsync.js'
import { fetchScreenDashboards } from '../services/accessService.js'

// Screens that have a real component, keyed by their metadata code.
//
// A small explicit map, not a dynamic component generator: it is easy to read,
// impossible to surprise you with, and a screen that is not listed still
// renders - as its dashboards, or as a placeholder. Building an application
// therefore means adding rows plus one entry here, never a new router.
const SCREEN_COMPONENTS = {
  EMPLOYEE_LIST: EmployeeListScreen,
  EMPLOYEE_PROFILE: EmployeeProfileScreen,
  MY_LEAVE: MyLeaveScreen,
  LEAVE_REQUESTS: LeaveRequestsScreen,
  LEAVE_APPROVAL: LeaveApprovalScreen,
  MY_ATTENDANCE: MyAttendanceScreen,
  TEAM_ATTENDANCE: TeamAttendanceScreen,
  TIMESHEET: TimesheetScreen,
  TIMESHEET_APPROVAL: TimesheetApprovalScreen,
  MY_EXPENSES: MyExpensesScreen,
  EXPENSE_APPROVAL: ExpenseApprovalScreen,
  // LEAVE_DASHBOARD, ATTENDANCE_DASHBOARD and EXPENSE_DASHBOARD are
  // deliberately absent. It has dashboards configured
  // All three have dashboards configured against them in metadata, so
  // MetadataScreen below already renders them from the database - a
  // hand-written dashboard page would be the hardcoding this whole design
  // exists to avoid.
}

// One screen inside an application.
//
// A screen either has dashboards configured against it, in which case they are
// rendered from metadata, or it does not, in which case it shows a placeholder.
// Either way this single component serves every screen in all eight
// applications - there is no per-screen page.
function ScreenView({ screen }) {
  const ScreenComponent = SCREEN_COMPONENTS[screen.code]

  if (ScreenComponent) {
    return <ScreenComponent screen={screen} />
  }

  return <MetadataScreen screen={screen} />
}

// A screen with no component of its own: render its dashboards, or say that
// it is a placeholder.
function MetadataScreen({ screen }) {
  const { data: dashboards, error, loading, reload } = useAsync(
    () => fetchScreenDashboards(screen.code),
    [screen.code],
  )

  return (
    <>
      <header className="page-header">
        <h1>{screen.name}</h1>
        <p className="muted small">
          <code>{screen.route}</code>
        </p>
      </header>

      {loading && <Loading label="Loading screen..." />}
      <ErrorMessage message={error} onRetry={reload} />

      {!loading && !error && dashboards && dashboards.length === 0 && (
        <Empty
          title="No dashboards on this screen yet"
          hint={`${screen.name} is a placeholder. Its functionality is built in a later stage.`}
        />
      )}

      {!loading && !error && dashboards &&
        dashboards.map((dashboard) => (
          <DashboardView key={dashboard.id} dashboard={dashboard} />
        ))}
    </>
  )
}

export default ScreenView
