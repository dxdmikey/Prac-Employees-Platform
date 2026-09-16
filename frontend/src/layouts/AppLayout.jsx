// The shell around every signed-in page: a dark navy sidebar with the
// navigation and the user, and a light content area with a header.
//
// Two kinds of thing appear in the sidebar, and it is worth keeping them
// distinct in your head:
//
//   * Platform shell items - Applications, Workflow demo, Administration,
//     Organisation, Workflows. These are the platform's own screens, not
//     business applications, so they are listed here.
//   * Business applications - never listed here. They come from
//     /api/access/me and are rendered by the launcher.
//
// The platform-admin items are shown only when the backend returned at least
// one platform-admin application for this user. That reads the
// `is_platform_admin_app` flag from the metadata - it never looks at role
// names, so marking a new application as admin-only in the database is enough.

const WORKSPACE_ITEMS = [
  { view: 'launcher', label: 'Applications' },
  { view: 'workflow-demo', label: 'Workflow demo' },
]

const PLATFORM_ITEMS = [
  { view: 'admin', label: 'Administration' },
  { view: 'organisation', label: 'Organisation' },
  { view: 'workflows', label: 'Workflows' },
]

function NavItem({ item, active, onNavigate }) {
  return (
    <button
      type="button"
      className={active ? 'nav-link nav-link--active' : 'nav-link'}
      onClick={() => onNavigate(item.view)}
      aria-current={active ? 'page' : undefined}
    >
      {item.label}
    </button>
  )
}

function AppLayout({ access, view, title, onNavigate, onLogout, children }) {
  const { user, applications } = access
  const canAdminister = applications.some((app) => app.is_platform_admin_app)

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="sidebar__brand">
          Employee Platform
          <span>Metadata-driven demo</span>
        </div>

        <nav className="sidebar__nav" aria-label="Platform">
          <div className="sidebar__section">Workspace</div>
          {WORKSPACE_ITEMS.map((item) => (
            <NavItem
              key={item.view}
              item={item}
              active={view === item.view}
              onNavigate={onNavigate}
            />
          ))}

          {canAdminister && (
            <>
              <div className="sidebar__section">Platform</div>
              {PLATFORM_ITEMS.map((item) => (
                <NavItem
                  key={item.view}
                  item={item}
                  active={view === item.view}
                  onNavigate={onNavigate}
                />
              ))}
            </>
          )}
        </nav>

        <div className="sidebar__user">
          <div className="sidebar__user-name">
            {user.first_name} {user.last_name}
          </div>
          <div className="sidebar__user-meta">{user.email}</div>
          <button
            type="button"
            className="button--ghost button--small"
            onClick={onLogout}
          >
            Sign out
          </button>
        </div>
      </aside>

      <div className="shell__body">
        <header className="shell__header">
          <span className="shell__header-title">{title}</span>
          <span className="muted small">Signed in as {user.username}</span>
        </header>

        <main className="shell__main">{children}</main>
      </div>
    </div>
  )
}

export default AppLayout
