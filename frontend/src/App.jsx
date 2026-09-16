import { useCallback, useEffect, useState } from 'react'
import AppLayout from './layouts/AppLayout.jsx'
import { ErrorMessage, Loading } from './components/StatusViews.jsx'
import AdminPage from './pages/AdminPage.jsx'
import ApplicationPage from './pages/ApplicationPage.jsx'
import LauncherPage from './pages/LauncherPage.jsx'
import LoginPage from './pages/LoginPage.jsx'
import OrganizationPage from './pages/OrganizationPage.jsx'
import WorkflowDemoPage from './pages/WorkflowDemoPage.jsx'
import WorkflowsPage from './pages/WorkflowsPage.jsx'
import { fetchMyAccess } from './services/accessService.js'
import { logout as logoutRequest } from './services/authService.js'
import { getToken } from './services/apiClient.js'

// The platform's own screens, keyed by the view name the sidebar navigates
// to. Business applications are NOT here - they are opened from the launcher
// and rendered by ApplicationPage from metadata.
//
// A plain object instead of a router library: five views do not yet justify
// one, and a lookup table is easier to read than a chain of conditions.
const VIEWS = {
  launcher: { title: 'Applications', Component: LauncherPage },
  'workflow-demo': { title: 'Workflow demo', Component: WorkflowDemoPage },
  admin: { title: 'Administration', Component: AdminPage },
  organisation: { title: 'Organisation', Component: OrganizationPage },
  workflows: { title: 'Workflows', Component: WorkflowsPage },
}

function App() {
  // access = the whole answer from /api/access/me: user, roles, permissions,
  // applications. Everything the UI shows is derived from it.
  const [access, setAccess] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [view, setView] = useState('launcher')
  const [openApplication, setOpenApplication] = useState(null)

  const loadAccess = useCallback(async () => {
    // No saved token means nobody is signed in - show the login page without
    // making a pointless request.
    if (!getToken()) {
      setAccess(null)
      setLoading(false)
      return
    }

    setLoading(true)
    setError('')
    try {
      setAccess(await fetchMyAccess())
    } catch (err) {
      // 401 means the saved token is no longer good; that is "signed out",
      // not an error to complain about.
      if (err.status === 401) {
        setAccess(null)
      } else {
        setError(err.message || 'Could not load your access.')
      }
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadAccess()
  }, [loadAccess])

  async function handleLogout() {
    await logoutRequest()
    setAccess(null)
    setView('launcher')
    setOpenApplication(null)
  }

  function handleNavigate(nextView) {
    // An unknown view falls back to the launcher rather than a blank page.
    setView(VIEWS[nextView] ? nextView : 'launcher')
    setOpenApplication(null)
  }

  if (loading) {
    return (
      <main className="page page--narrow">
        <Loading label="Loading your workspace..." />
      </main>
    )
  }

  if (error) {
    return (
      <main className="page page--narrow">
        <ErrorMessage message={error} onRetry={loadAccess} />
        <button type="button" className="button--secondary" onClick={handleLogout}>
          Sign out
        </button>
      </main>
    )
  }

  if (!access) {
    // After a successful login, reload the access metadata rather than
    // guessing it from the login response.
    return <LoginPage onLoggedIn={loadAccess} />
  }

  const current = VIEWS[view] ?? VIEWS.launcher
  const { Component } = current

  return (
    <AppLayout
      access={access}
      view={openApplication ? 'launcher' : view}
      title={openApplication ? openApplication.name : current.title}
      onNavigate={handleNavigate}
      onLogout={handleLogout}
    >
      {openApplication ? (
        <ApplicationPage
          application={openApplication}
          onBack={() => setOpenApplication(null)}
        />
      ) : (
        <Component access={access} onOpenApplication={setOpenApplication} />
      )}
    </AppLayout>
  )
}

export default App
