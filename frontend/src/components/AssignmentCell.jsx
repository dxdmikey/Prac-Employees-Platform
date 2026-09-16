// A table cell for "these things are assigned, and here is how to add another".
//
// Roles and business units are administered identically - a list of removable
// badges plus a dropdown and an Assign button - so both use this one component
// rather than two copies of the same JSX.

function AssignmentCell({
  items,
  options,
  optionLabel = 'item',
  emptyLabel,
  busy,
  selectedValue,
  onSelect,
  onAssign,
  onRemove,
  selectAriaLabel,
}) {
  return (
    <>
      {items.length === 0 ? (
        <span className="muted small">{emptyLabel}</span>
      ) : (
        <div className="badge-row">
          {items.map((item) => (
            <span key={item.id} className="badge">
              {item.name}
              <button
                type="button"
                className="badge__remove"
                title={`Remove ${item.name}`}
                disabled={busy}
                onClick={() => onRemove(item)}
              >
                &times;
              </button>
            </span>
          ))}
        </div>
      )}

      <div className="row-actions row-actions--stacked">
        <select
          value={selectedValue ?? ''}
          disabled={busy}
          aria-label={selectAriaLabel}
          onChange={(event) => onSelect(event.target.value)}
        >
          <option value="">Select {optionLabel}...</option>
          {options.map((option) => (
            <option key={option.id} value={option.id}>
              {option.name}
            </option>
          ))}
        </select>
        <button
          type="button"
          className="button--small"
          disabled={busy}
          onClick={onAssign}
        >
          {busy ? 'Saving...' : 'Assign'}
        </button>
      </div>
    </>
  )
}

export default AssignmentCell
