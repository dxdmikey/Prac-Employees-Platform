"""
Association ("join") tables for the four many-to-many relationships.

A relational database cannot put a list inside a column, so "a user has many
roles and a role has many users" is stored as a third table holding one row per
pairing. Each row here means "this thing is linked to that thing".

These are plain SQLAlchemy Table objects rather than full model classes,
because they carry nothing but the two foreign keys and a timestamp. That keeps
them light and lets the models say relationship(secondary=...) for natural
navigation such as user.roles or role.permissions.

Every one uses a composite primary key of its two foreign keys. That does two
jobs at once: it identifies the row, and it makes a duplicate pairing
impossible - the same role cannot be granted to the same user twice.
"""

from sqlalchemy import Column, DateTime, ForeignKey, Table, func

from app.db.base import Base

# users <-> roles
user_roles = Table(
    "user_roles",
    Base.metadata,
    Column("user_id", ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("role_id", ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
    Column("assigned_at", DateTime(timezone=True),
           server_default=func.now(), nullable=False),
)

# roles <-> permissions
role_permissions = Table(
    "role_permissions",
    Base.metadata,
    Column("role_id", ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
    Column("permission_id", ForeignKey("permissions.id", ondelete="CASCADE"),
           primary_key=True),
    Column("created_at", DateTime(timezone=True),
           server_default=func.now(), nullable=False),
)

# roles <-> applications
role_applications = Table(
    "role_applications",
    Base.metadata,
    Column("role_id", ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
    Column("application_id", ForeignKey("applications.id", ondelete="CASCADE"),
           primary_key=True),
    Column("created_at", DateTime(timezone=True),
           server_default=func.now(), nullable=False),
)

# roles <-> screens
#
# Applications answer "which app may this role open?"; screens answer "which
# pages inside it?". They are separate tables because the two questions have
# different answers - a Manager may open Expense Management but not the
# Expense Approval screen inside it.
role_screens = Table(
    "role_screens",
    Base.metadata,
    Column("role_id", ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
    Column("screen_id", ForeignKey("screens.id", ondelete="CASCADE"),
           primary_key=True),
    Column("created_at", DateTime(timezone=True),
           server_default=func.now(), nullable=False),
)

# users <-> business_units
user_business_units = Table(
    "user_business_units",
    Base.metadata,
    Column("user_id", ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("business_unit_id", ForeignKey("business_units.id", ondelete="CASCADE"),
           primary_key=True),
    Column("assigned_at", DateTime(timezone=True),
           server_default=func.now(), nullable=False),
)

# workflow_transitions <-> roles
#
# Which roles may perform a transition. This reuses the RBAC roles rather than
# inventing a second permission system for workflows: "only a Manager may
# approve" is a row here, not a line of Python.
workflow_transition_roles = Table(
    "workflow_transition_roles",
    Base.metadata,
    Column("transition_id", ForeignKey("workflow_transitions.id", ondelete="CASCADE"),
           primary_key=True),
    Column("role_id", ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
    Column("created_at", DateTime(timezone=True),
           server_default=func.now(), nullable=False),
)
