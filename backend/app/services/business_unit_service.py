"""
Business unit hierarchy and organisational scope.

RBAC answers *what* a user may do. This service answers *where* they may do it.
The two are deliberately separate: a Manager role says "may approve expenses",
a Branch 1 assignment says "for Branch 1 and everything under it".

The organisation is one self-referencing table using the **adjacency list**
pattern - each row stores only its parent. No closure tables, no nested sets,
no materialised paths: one column, `parent_id`, and a recursive query to walk
it. That keeps moving a unit to a new parent a single UPDATE.

The inheritance rule, in one line:

    an assignment grants the unit **and everything beneath it**, never above.

So Company 1 sees its branches and their departments; Branch 1 does not see
Company 1.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session, aliased, selectinload

from app.models.business_unit import BusinessUnit
from app.models.business_unit_type import BusinessUnitType
from app.models.user import User


class BusinessUnitError(Exception):
    """Raised when a hierarchy operation would produce invalid data."""


# ---------------------------------------------------------------------------
# Reading the tree
# ---------------------------------------------------------------------------


def list_business_unit_types(db: Session) -> list[BusinessUnitType]:
    return list(
        db.scalars(
            select(BusinessUnitType).order_by(
                BusinessUnitType.display_order, BusinessUnitType.name
            )
        )
    )


def list_business_units(db: Session) -> list[BusinessUnit]:
    """Every business unit as a flat list, parents before children."""
    return list(
        db.scalars(
            select(BusinessUnit)
            .options(selectinload(BusinessUnit.business_unit_type))
            .order_by(BusinessUnit.parent_id.nulls_first(), BusinessUnit.code)
        )
    )


def get_descendant_ids(
    db: Session, root_ids: set[int] | list[int], include_self: bool = True
) -> set[int]:
    """
    Every unit at or beneath the given units, using one recursive query.

    How the recursive CTE works, in three parts:

      1. **Anchor.** Start with the rows we were given - the roots of the walk.
      2. **Recursive step.** Find every row whose parent_id matches something
         already collected. UNION ALL adds them to the same result set.
      3. **Repeat** until a pass finds nothing new. PostgreSQL does the looping.

    In SQL it reads:

        WITH RECURSIVE descendants AS (
            SELECT id FROM business_units WHERE id IN (:roots)   -- anchor
            UNION ALL
            SELECT child.id                                      -- recursive
              FROM business_units AS child
              JOIN descendants ON child.parent_id = descendants.id
        )
        SELECT id FROM descendants;

    One query returns the whole subtree at any depth - adding a fifth level to
    the organisation needs no code change here.
    """
    root_ids = list(root_ids)
    if not root_ids:
        return set()

    # 1. the anchor
    descendants = (
        select(BusinessUnit.id)
        .where(BusinessUnit.id.in_(root_ids))
        .cte(name="descendants", recursive=True)
    )

    # 2. the recursive step - children of anything already collected
    child = aliased(BusinessUnit)
    descendants = descendants.union_all(
        select(child.id).join(descendants, child.parent_id == descendants.c.id)
    )

    found = set(db.scalars(select(descendants.c.id)))
    if not include_self:
        found -= set(root_ids)
    return found


def get_ancestor_ids(db: Session, unit_id: int) -> list[int]:
    """
    Every unit above this one, nearest parent first.

    Used for breadcrumbs and for the cycle check when re-parenting. This walks
    *up* the tree, which never grants access - it is only for display and
    validation.
    """
    ancestors: list[int] = []
    seen: set[int] = {unit_id}
    current = db.get(BusinessUnit, unit_id)

    while current is not None and current.parent_id is not None:
        if current.parent_id in seen:
            break                      # defensive: never loop on bad data
        ancestors.append(current.parent_id)
        seen.add(current.parent_id)
        current = db.get(BusinessUnit, current.parent_id)

    return ancestors


def build_tree(db: Session, units: list[BusinessUnit] | None = None) -> list[dict]:
    """
    Turn the flat list into nested dictionaries the frontend can render.

    Done in Python rather than SQL because it is one pass over a small list and
    far easier to read: index every unit by id, then attach each one to its
    parent. Anything without a parent (or whose parent is not in the list) is
    a root.
    """
    units = list_business_units(db) if units is None else units

    nodes: dict[int, dict] = {
        unit.id: {
            "id": unit.id,
            "code": unit.code,
            "name": unit.name,
            "parent_id": unit.parent_id,
            "business_unit_type_id": unit.business_unit_type_id,
            "business_unit_type_code": unit.business_unit_type.code,
            "business_unit_type_name": unit.business_unit_type.name,
            "is_active": unit.is_active,
            "children": [],
        }
        for unit in units
    }

    roots: list[dict] = []
    for unit in units:
        node = nodes[unit.id]
        parent = nodes.get(unit.parent_id) if unit.parent_id else None
        if parent is None:
            roots.append(node)
        else:
            parent["children"].append(node)

    return roots


# ---------------------------------------------------------------------------
# Who can see what
# ---------------------------------------------------------------------------


def get_user_business_units(db: Session, user: User) -> list[BusinessUnit]:
    """The units a user is *directly* assigned to - no inheritance."""
    return sorted(user.business_units, key=lambda unit: unit.code)


def get_user_visible_business_unit_ids(db: Session, user: User) -> set[int]:
    """The ids a user can see: their assignments plus every descendant."""
    assigned = [unit.id for unit in user.business_units]
    return get_descendant_ids(db, assigned, include_self=True)


def get_user_visible_business_units(db: Session, user: User) -> list[BusinessUnit]:
    """
    The units a user can see, as rows.

    Inactive units are filtered out here rather than during the walk, so
    deactivating a middle unit does not hide the branches underneath it.
    """
    visible_ids = get_user_visible_business_unit_ids(db, user)
    if not visible_ids:
        return []

    return list(
        db.scalars(
            select(BusinessUnit)
            .options(selectinload(BusinessUnit.business_unit_type))
            .where(BusinessUnit.id.in_(visible_ids), BusinessUnit.is_active.is_(True))
            .order_by(BusinessUnit.parent_id.nulls_first(), BusinessUnit.code)
        )
    )


def can_access_business_unit(db: Session, user: User, business_unit_id: int) -> bool:
    """
    May this user see this unit?

    True when the unit is one of their assignments, or sits beneath one.
    Being *above* an assignment is never enough.
    """
    return business_unit_id in get_user_visible_business_unit_ids(db, user)


# ---------------------------------------------------------------------------
# Changing assignments
# ---------------------------------------------------------------------------


def assign_business_unit_to_user(
    db: Session, user: User, unit: BusinessUnit
) -> bool:
    """Assign a unit to a user. Returns False if they already had it."""
    if unit in user.business_units:
        return False
    user.business_units.append(unit)
    db.commit()
    return True


def remove_business_unit_from_user(
    db: Session, user: User, unit: BusinessUnit
) -> bool:
    """Remove an assignment. Returns False if it was not there."""
    if unit not in user.business_units:
        return False
    user.business_units.remove(unit)
    db.commit()
    return True


# ---------------------------------------------------------------------------
# Changing the tree, with validation
# ---------------------------------------------------------------------------


def _validate_parent(db: Session, unit_id: int | None, parent_id: int | None) -> None:
    """
    Refuse a parent that would break the tree.

    Two ways it can break:

      * **Self-parenting** - a unit that is its own parent.
      * **A cycle** - making a unit the child of one of its own descendants,
        e.g. Company 1 under Department 1. The tree would then have a loop with
        no root, and walking it would never end.

    The cycle check asks the descendant query directly: if the proposed parent
    is somewhere beneath this unit, the move is illegal.
    """
    if parent_id is None:
        return

    if db.get(BusinessUnit, parent_id) is None:
        raise BusinessUnitError(f"No business unit with id {parent_id}.")

    if unit_id is None:
        return                                   # a brand-new unit has no subtree

    if parent_id == unit_id:
        raise BusinessUnitError("A business unit cannot be its own parent.")

    if parent_id in get_descendant_ids(db, [unit_id], include_self=False):
        raise BusinessUnitError(
            "That parent sits below this business unit, which would create a "
            "cycle in the hierarchy."
        )


def create_business_unit(
    db: Session,
    *,
    code: str,
    name: str,
    business_unit_type_id: int,
    parent_id: int | None,
    description: str | None = None,
) -> BusinessUnit:
    if db.scalar(select(BusinessUnit).where(BusinessUnit.code == code)):
        raise BusinessUnitError(f"A business unit with code {code} already exists.")
    if db.get(BusinessUnitType, business_unit_type_id) is None:
        raise BusinessUnitError(
            f"No business unit type with id {business_unit_type_id}."
        )

    _validate_parent(db, None, parent_id)

    unit = BusinessUnit(
        code=code,
        name=name,
        business_unit_type_id=business_unit_type_id,
        parent_id=parent_id,
        description=description,
    )
    db.add(unit)
    db.commit()
    return unit


def update_business_unit(
    db: Session,
    unit: BusinessUnit,
    *,
    name: str | None = None,
    business_unit_type_id: int | None = None,
    parent_id: int | None = None,
    description: str | None = None,
    is_active: bool | None = None,
    reparent: bool = False,
) -> BusinessUnit:
    """
    Update a unit. `reparent=True` is required to change parent_id, so that
    leaving it out of a request never silently moves a unit to a root.
    """
    if reparent:
        _validate_parent(db, unit.id, parent_id)
        unit.parent_id = parent_id

    if business_unit_type_id is not None:
        if db.get(BusinessUnitType, business_unit_type_id) is None:
            raise BusinessUnitError(
                f"No business unit type with id {business_unit_type_id}."
            )
        unit.business_unit_type_id = business_unit_type_id

    if name is not None:
        unit.name = name
    if description is not None:
        unit.description = description
    if is_active is not None:
        unit.is_active = is_active

    db.commit()
    return unit


def delete_business_unit(db: Session, unit: BusinessUnit) -> None:
    """
    Delete a unit, but never one that still has children.

    The database enforces this too (the foreign key is ON DELETE RESTRICT);
    checking here lets us return a clear message instead of a raw constraint
    error. Move or delete the children first.
    """
    child_count = len(get_descendant_ids(db, [unit.id], include_self=False))
    if child_count:
        raise BusinessUnitError(
            f"{unit.name} still has {child_count} business unit(s) beneath it. "
            "Move or delete them first."
        )

    db.delete(unit)
    db.commit()
