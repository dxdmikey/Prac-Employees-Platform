"""Dashboard model - a chart or widget configuration placed on a screen."""

from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.dashboard_widget import DashboardWidget
    from app.models.screen import Screen


class Dashboard(Base, TimestampMixin):
    """A dashboard belongs to exactly one screen (one-to-many)."""

    __tablename__ = "dashboards"
    __table_args__ = (
        UniqueConstraint("screen_id", "code", name="uq_dashboards_screen_code"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # As on screens: UNIQUE(screen_id, code) already indexes screen_id first,
    # so this index is redundant today but kept so the foreign key stays
    # indexed independently of that constraint.
    screen_id: Mapped[int] = mapped_column(
        ForeignKey("screens.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    # JSONB (not plain JSON) is PostgreSQL's binary JSON type: it is stored
    # parsed, so it is faster to query and can be indexed. This column will
    # eventually hold the ECharts option object plus the query definition that
    # feeds it - which is why it is free-form JSON rather than fixed columns.
    config_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False,
                                            default=True, server_default="true")
    display_order: Mapped[int] = mapped_column(Integer, nullable=False,
                                               default=0, server_default="0")

    screen: Mapped["Screen"] = relationship(back_populates="dashboards")

    # Deleting a dashboard deletes its widgets - a widget cannot exist alone.
    widgets: Mapped[list["DashboardWidget"]] = relationship(
        back_populates="dashboard",
        cascade="all, delete-orphan",
        order_by="DashboardWidget.display_order",
    )

    def __repr__(self) -> str:
        return f"<Dashboard id={self.id} code={self.code!r}>"
