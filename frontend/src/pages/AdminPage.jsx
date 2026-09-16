import { useState } from 'react'
import AssignmentCell from '../components/AssignmentCell.jsx'
import { Empty, ErrorMessage, Loading } from '../components/StatusViews.jsx'
import { useAsync } from '../hooks/useAsync.js'
import { assignRole, fetchRoles, fetchUsers, removeRole } from '../services/adminService.js'
import {
  assignBusinessUnit,
  fetchBusinessUnits,
  removeBusinessUnit,
} from '../services/organizationService.js'

// The platform administration screen: who a person is, what they may do, and
// where they may do it.
//
// Roles and business units are deliberately shown side by side, because they
// are the two independent halves of authorisation:
//
//   roles          -> WHAT   (permissions, applications, screens)
//   business units -> WHERE  (this unit and everything beneath it)
//
// Neither implies the other. Adding a role never widens someone's
// organisational scope, and adding a business unit never grants a permission.
function AdminPage() {
  const usersRequest = useAsync(fetchUsers, [])
  const rolesRequest = useAsync(fetchRoles, [])
  const unitsRequest = useAsync(fetchBusinessUnits, [])

  // Per-user overrides, so a row can be redrawn from an API response without
  // re-fetching the whole table.
  const [assigned, setAssigned] = useState({ role: {}, unit: {} })
  const [selected, setSelected] = useState({ role: {}, unit: {} })
  const [busyUserId, setBusyUserId] = useState(null)
  const [actionError, setActionError] = useState('')

  const users = usersRequest.data ?? []
  const roles = rolesRequest.data ?? []
  const units = unitsRequest.data ?? []
  const loading = usersRequest.loading || rolesRequest.loading || unitsRequest.loading
  const loadError = usersRequest.error || rolesRequest.error || unitsRequest.error

  function reloadAll() {
    usersRequest.reload()
    rolesRequest.reload()
    unitsRequest.reload()
  }

  function choose(kind, userId, value) {
    setSelected((current) => ({
      ...current,
      [kind]: { ...current[kind], [userId]: value },
    }))
  }

  // One handler for every change: whatever happens, the busy flag is cleared,
  // so a failed request can never leave a row disabled forever.
  async function runChange(kind, user, action) {
    setBusyUserId(user.id)
    setActionError('')
    try {
      const updated = await action()
      setAssigned((current) => ({
        ...current,
        [kind]: { ...current[kind], [user.id]: updated },
      }))
    } catch (err) {
      setActionError(err.message || 'The change could not be saved.')
    } finally {
      setBusyUserId(null)
    }
  }

  function assign(kind, user, assignFn, noun) {
    const id = Number(selected[kind][user.id])
    if (!id) {
      setActionError(`Choose a ${noun} to assign first.`)
      return
    }
    runChange(kind, user, () => assignFn(user.id, id))
  }

  return (
    <>
      <header className="page-header">
        <h1>Administration</h1>
        <p className="muted">
          Roles decide <strong>what</strong> a person may do. Business units
          decide <strong>where</strong>. Changes take effect on their next
          request.
        </p>
      </header>

      {loading && <Loading label="Loading users, roles and business units..." />}
      <ErrorMessage message={loadError} onRetry={reloadAll} />
      <ErrorMessage message={actionError} />

      {!loading && !loadError && users.length === 0 && (
        <Empty title="No users found" hint="Create one with scripts/create_admin_user.py." />
      )}

      {!loading && !loadError && users.length > 0 && (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>User</th>
                <th>Roles &mdash; what they may do</th>
                <th>Business units &mdash; where</th>
              </tr>
            </thead>
            <tbody>
              {users.map((user) => {
                const busy = busyUserId === user.id
                return (
                  <tr key={user.id}>
                    <td>
                      <strong>{user.username}</strong>
                      <div className="muted small">
                        {user.first_name} {user.last_name}
                        {!user.is_active && ' - inactive'}
                      </div>
                      <div className="muted small">{user.email}</div>
                    </td>

                    <td>
                      <AssignmentCell
                        items={assigned.role[user.id] ?? user.roles}
                        options={roles}
                        optionLabel="role"
                        emptyLabel="No roles"
                        busy={busy}
                        selectedValue={selected.role[user.id]}
                        selectAriaLabel={`Role to assign to ${user.username}`}
                        onSelect={(value) => choose('role', user.id, value)}
                        onAssign={() => assign('role', user, assignRole, 'role')}
                        onRemove={(role) =>
                          runChange('role', user, () => removeRole(user.id, role.id))
                        }
                      />
                    </td>

                    <td>
                      <AssignmentCell
                        items={assigned.unit[user.id] ?? user.business_units}
                        options={units}
                        optionLabel="business unit"
                        emptyLabel="No business units"
                        busy={busy}
                        selectedValue={selected.unit[user.id]}
                        selectAriaLabel={`Business unit to assign to ${user.username}`}
                        onSelect={(value) => choose('unit', user.id, value)}
                        onAssign={() =>
                          assign('unit', user, assignBusinessUnit, 'business unit')
                        }
                        onRemove={(unit) =>
                          runChange('unit', user, () =>
                            removeBusinessUnit(user.id, unit.id),
                          )
                        }
                      />
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </>
  )
}

export default AdminPage
