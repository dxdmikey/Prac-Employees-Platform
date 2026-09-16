// Small reusable pieces for the three states every async screen has:
// still loading, something went wrong, or there is nothing to show.
//
// Having them in one file keeps the pages short and makes every screen in the
// app behave and look the same.

export function Loading({ label = 'Loading...' }) {
  return (
    <div className="status status--loading" role="status">
      <span className="spinner" aria-hidden="true" />
      <span>{label}</span>
    </div>
  )
}

export function ErrorMessage({ message, onRetry }) {
  if (!message) return null
  return (
    <div className="status status--error" role="alert">
      <span>{message}</span>
      {onRetry && (
        <button type="button" className="button--secondary button--small" onClick={onRetry}>
          Try again
        </button>
      )}
    </div>
  )
}

export function Empty({ title, hint }) {
  return (
    <div className="status status--empty">
      <strong>{title}</strong>
      {hint && <span className="muted">{hint}</span>}
    </div>
  )
}
