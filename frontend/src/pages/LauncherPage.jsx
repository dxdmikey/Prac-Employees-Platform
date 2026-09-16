import { Empty } from '../components/StatusViews.jsx'

// The metadata carries an `icon` name, but the project has no icon font and
// this task is not the place to add one. Until then, the first letters of the
// application name make a recognisable tile.
function monogram(name) {
  return name
    .split(/[\s&-]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((word) => word[0].toUpperCase())
    .join('')
}

// The application launcher.
//
// Notice what is NOT here: no list of application names, and no checks like
// `if (user.role === 'HR')`. The cards below are drawn from whatever the
// backend returned in /api/access/me. Grant a role a new application in the
// database and it appears here on the next login - no code change.
function LauncherPage({ access, onOpenApplication }) {
  // total_applications is how many active applications the platform has.
  // It comes from the backend so the denominator is never a number typed in
  // here - add a ninth application to the seed and "of 8" becomes "of 9".
  const { applications, roles, permissions, total_applications: total } = access

  return (
    <>
      <header className="page-header">
        <h1>Your applications</h1>
        <p className="muted">
          {applications.length === 0
            ? 'No applications are assigned to your roles.'
            : `${applications.length} of ${total} applications are available to you.`}
        </p>
      </header>

      {applications.length === 0 ? (
        <Empty
          title="Nothing assigned yet"
          hint="Your roles do not grant access to any application. Ask a platform administrator to assign one."
        />
      ) : (
        <div className="card-grid">
          {applications.map((application) => (
            <button
              key={application.code}
              type="button"
              className="app-card"
              onClick={() => onOpenApplication(application)}
            >
              <span className="app-card__icon" aria-hidden="true">
                {monogram(application.name)}
              </span>
              <span className="app-card__name">{application.name}</span>
              <span className="app-card__description">{application.description}</span>
              {application.is_platform_admin_app && (
                <span className="badge badge--admin">Platform admin</span>
              )}
            </button>
          ))}
        </div>
      )}

      <section className="panel">
        <h2>Why you see these</h2>
        <p className="muted">
          Access comes from your roles, not from anything written into this page.
        </p>
        <dl className="details">
          <dt>Roles</dt>
          <dd>
            {roles.length === 0
              ? '(none)'
              : roles.map((role) => (
                  <span key={role.code} className="badge">
                    {role.name}
                  </span>
                ))}
          </dd>
          <dt>Permissions</dt>
          <dd>
            {permissions.length === 0
              ? '(none)'
              : permissions.map((permission) => (
                  <span key={permission.code} className="badge badge--muted">
                    {permission.code}
                  </span>
                ))}
          </dd>
        </dl>
      </section>
    </>
  )
}

export default LauncherPage
