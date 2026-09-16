import { useState } from 'react'

// A recursive tree component.
//
// The trick is that TreeNode renders itself for each of its children. One
// small component therefore draws a hierarchy of any depth - which mirrors
// the database, where one self-referencing table stores every level.
//
// Nothing here knows what a "Company" or a "Department" is. The nodes, their
// names and their types all come from /api/business-units/tree.

function TreeNode({ node, depth, selectedId, onSelect }) {
  const hasChildren = node.children.length > 0
  // Everything starts expanded so the shape of the organisation is visible
  // immediately; deep trees can be collapsed as needed.
  const [expanded, setExpanded] = useState(true)

  return (
    <li className="tree__item">
      <div
        className={
          selectedId === node.id ? 'tree__row tree__row--selected' : 'tree__row'
        }
        style={{ paddingLeft: `${depth * 20 + 8}px` }}
      >
        {hasChildren ? (
          <button
            type="button"
            className="tree__toggle"
            onClick={() => setExpanded((open) => !open)}
            aria-expanded={expanded}
            aria-label={expanded ? `Collapse ${node.name}` : `Expand ${node.name}`}
          >
            {expanded ? '▾' : '▸'}
          </button>
        ) : (
          // A leaf gets a dot, so its label still lines up with its siblings.
          <span className="tree__leaf" aria-hidden="true">
            &bull;
          </span>
        )}

        <button
          type="button"
          className="tree__label"
          onClick={() => onSelect && onSelect(node)}
        >
          <span className="tree__name">{node.name}</span>
          <span className="badge badge--muted">{node.business_unit_type_name}</span>
          {!node.is_active && <span className="badge badge--muted">Inactive</span>}
        </button>
      </div>

      {hasChildren && expanded && (
        <ul className="tree__children">
          {node.children.map((child) => (
            <TreeNode
              key={child.id}
              node={child}
              depth={depth + 1}
              selectedId={selectedId}
              onSelect={onSelect}
            />
          ))}
        </ul>
      )}
    </li>
  )
}

function BusinessUnitTree({ nodes, selectedId, onSelect }) {
  return (
    <ul className="tree">
      {nodes.map((node) => (
        <TreeNode
          key={node.id}
          node={node}
          depth={0}
          selectedId={selectedId}
          onSelect={onSelect}
        />
      ))}
    </ul>
  )
}

export default BusinessUnitTree
