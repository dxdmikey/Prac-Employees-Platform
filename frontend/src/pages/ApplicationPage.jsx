import { useEffect, useState } from 'react'
import ScreenView from '../components/ScreenView.jsx'
import { Empty, ErrorMessage, Loading } from '../components/StatusViews.jsx'
import { useAsync } from '../hooks/useAsync.js'
import { fetchApplicationScreens } from '../services/accessService.js'

// The application shell: a title, the screen navigation, and the selected
// screen's content.
//
// This one component serves all eight applications. There is no Payroll page
// and no Leave page - opening Payroll asks the backend which Payroll screens
// this user may see, and renders whatever comes back. Two people opening the
// same application can legitimately get different navigation.
function ApplicationPage({ application, onBack }) {
  const { data: screens, error, loading, reload } = useAsync(
    () => fetchApplicationScreens(application.code),
    [application.code],
  )

  const [selectedCode, setSelectedCode] = useState(null)

  // Open the first screen the backend returned. Which screen that is depends
  // on the user's roles, so it is not decided here.
  useEffect(() => {
    if (screens && screens.length > 0) {
      setSelectedCode((current) =>
        screens.some((s) => s.code === current) ? current : screens[0].code,
      )
    }
  }, [screens])

  const selected = screens?.find((screen) => screen.code === selectedCode) ?? null

  return (
    <>
      <div className="app-header">
        <button type="button" className="link-button" onClick={onBack}>
          &larr; All applications
        </button>
        <h1>{application.name}</h1>
        <p className="muted small">{application.description}</p>
      </div>

      {loading && <Loading label="Loading screens..." />}
      <ErrorMessage message={error} onRetry={reload} />

      {!loading && !error && screens && screens.length === 0 && (
        <Empty
          title="No screens available"
          hint="You can open this application, but none of its screens are assigned to your roles."
        />
      )}

      {!loading && !error && screens && screens.length > 0 && (
        <div className="app-shell">
          {/* Application navigation, built from metadata. */}
          <nav className="screen-nav" aria-label={`${application.name} screens`}>
            {screens.map((screen) => (
              <button
                key={screen.code}
                type="button"
                className={
                  screen.code === selectedCode
                    ? 'screen-nav__link screen-nav__link--active'
                    : 'screen-nav__link'
                }
                onClick={() => setSelectedCode(screen.code)}
                aria-current={screen.code === selectedCode ? 'page' : undefined}
              >
                {screen.name}
              </button>
            ))}
          </nav>

          <div className="app-shell__content">
            {selected && <ScreenView screen={selected} />}
          </div>
        </div>
      )}
    </>
  )
}

export default ApplicationPage
