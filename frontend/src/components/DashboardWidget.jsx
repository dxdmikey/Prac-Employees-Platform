import EChart, { buildChartOption } from './EChart.jsx'

// Renders one widget from its metadata.
//
// The whole metadata-driven dashboard idea lives in the switch below: the
// database says `widget_type`, and this picks the component. Adding a new kind
// of tile means one case here plus rows in the database - never a new
// dashboard page. A small explicit mapping, not a dynamic component generator.

function formatValue(value, unit) {
  if (typeof value !== 'number') return String(value ?? '-')
  const formatted = value.toLocaleString('en-US')
  return unit === 'currency' ? `$${formatted}` : formatted
}

function StatWidget({ config }) {
  return (
    <div className="widget__stat">
      <div className="widget__stat-value">{formatValue(config.value, config.unit)}</div>
      {config.caption && <div className="muted small">{config.caption}</div>}
    </div>
  )
}

function TableWidget({ config }) {
  const columns = config.columns ?? []
  const rows = config.rows ?? []
  if (rows.length === 0) return <p className="muted small">No rows configured.</p>

  return (
    <div className="table-wrap table-wrap--flush">
      <table className="table">
        <thead>
          <tr>
            {columns.map((column) => (
              <th key={column}>{column}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, rowIndex) => (
            // Sample rows have no id of their own, so the index is the key.
            <tr key={rowIndex}>
              {row.map((cell, cellIndex) => (
                <td key={cellIndex}>{cell}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// The tile itself: title plus body, spanning the columns the metadata asks
// for. Used for the loading state and the real content alike, so the grid
// never jumps when data arrives.
function WidgetFrame({ widget, children }) {
  const isChart = ['bar', 'line', 'pie'].includes(widget.widget_type)
  return (
    <article
      className={isChart ? 'widget widget--chart' : 'widget'}
      style={{ gridColumn: `span ${Math.min(widget.width || 3, 12)}` }}
    >
      <h3 className="widget__title">{widget.title}</h3>
      {children}
    </article>
  )
}

function DashboardWidget({ widget, data, loading }) {
  // Live values win over stored sample values; a widget with no data source
  // has no `data` and keeps its configured numbers.
  const config = { ...(widget.config_json ?? {}), ...(data ?? {}) }

  if (loading) {
    return (
      <WidgetFrame widget={widget}>
        <span className="muted small">Loading...</span>
      </WidgetFrame>
    )
  }

  let body
  switch (widget.widget_type) {
    case 'stat':
      body = <StatWidget config={config} />
      break
    case 'bar':
    case 'line':
    case 'pie':
      body = <EChart option={buildChartOption(widget.widget_type, config)} />
      break
    case 'table':
      body = <TableWidget config={config} />
      break
    default:
      // An unknown type must never break the page.
      body = (
        <p className="muted small">
          No renderer for widget type <code>{widget.widget_type}</code> yet.
        </p>
      )
  }

  return <WidgetFrame widget={widget}>{body}</WidgetFrame>
}

export default DashboardWidget
