import DashboardWidget from './DashboardWidget.jsx'
import { ErrorMessage } from './StatusViews.jsx'
import { useAsync } from '../hooks/useAsync.js'
import { fetchDashboardData } from '../services/accessService.js'

// One dashboard: a title and its widgets on a 12-column grid.
//
// Two sources feed a widget. Its *shape* - title, chart type, width, order -
// always comes from metadata. Its *numbers* come from metadata too, unless the
// widget declares a data_source, in which case the backend supplies live
// values scoped to this user and they are merged over the stored config.
function DashboardView({ dashboard }) {
  const widgets = dashboard.widgets ?? []

  // Only ask for live data if at least one widget wants it.
  const needsData = widgets.some((w) => w.config_json?.data_source)
  const dataRequest = useAsync(
    () => (needsData ? fetchDashboardData(dashboard.code) : Promise.resolve({})),
    [dashboard.code, needsData],
  )
  const liveData = dataRequest.data ?? {}

  return (
    <section className="dashboard">
      <header className="dashboard__header">
        <h2>{dashboard.name}</h2>
        {dashboard.description && (
          <p className="muted small">{dashboard.description}</p>
        )}
      </header>

      <ErrorMessage message={dataRequest.error} onRetry={dataRequest.reload} />

      {widgets.length === 0 ? (
        <p className="muted small">This dashboard has no widgets configured.</p>
      ) : (
        <div className="widget-grid">
          {widgets.map((widget) => (
            <DashboardWidget
              key={widget.id}
              widget={widget}
              data={liveData[widget.code]}
              loading={dataRequest.loading && Boolean(widget.config_json?.data_source)}
            />
          ))}
        </div>
      )}
    </section>
  )
}

export default DashboardView
