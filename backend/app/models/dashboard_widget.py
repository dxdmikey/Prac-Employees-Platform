"""DashboardWidget model - one tile on a dashboard."""

from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.dashboard import Dashboard


class DashboardWidget(Base, TimestampMixin):
    """
    A single tile: a statistic, a chart or a table.

    This is the last link in the metadata chain:

        Application -> Screen -> Dashboard -> Widget

    A widget is configuration, not code. `widget_type` tells the frontend which
    component to render, and `config_json` carries everything that component
    needs. Adding a chart to a dashboard is therefore an INSERT - React is not
    touched, and no dashboard is ever written as a hardcoded page.
    """

    __tablename__ = "dashboard_widgets"
    __table_args__ = (
        UniqueConstraint("dashboard_id", "code", name="uq_dashboard_widgets_code"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    # As elsewhere, UNIQUE(dashboard_id, code) already indexes dashboard_id
    # first; the explicit index keeps the foreign key indexed on its own.
    dashboard_id: Mapped[int] = mapped_column(
        ForeignKey("dashboards.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    code: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(150), nullable=False)

    # One of: stat, bar, line, pie, table.
    #
    # Deliberately a plain string, not a database enum: adding a widget type
    # should be a new React component plus new rows, never a migration.
    widget_type: Mapped[str] = mapped_column(String(30), nullable=False)

    # Everything the widget needs to draw itself. The shape depends on the
    # type, e.g. {"value": 128, "label": "Employees"} for a stat, or
    # {"categories": [...], "series": [...]} for a bar chart.
    #
    # At this stage the sample values live here too, so a dashboard can be
    # rendered end to end before any real analytics query exists.
    config_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    # Simple grid placement. The frontend reads width as a number of columns
    # out of 12, which is enough for a tidy layout without a layout engine.
    grid_x: Mapped[int] = mapped_column(Integer, nullable=False,
                                        default=0, server_default="0")
    grid_y: Mapped[int] = mapped_column(Integer, nullable=False,
                                        default=0, server_default="0")
    width: Mapped[int] = mapped_column(Integer, nullable=False,
                                       default=3, server_default="3")
    height: Mapped[int] = mapped_column(Integer, nullable=False,
                                        default=1, server_default="1")

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False,
                                            default=True, server_default="true")
    display_order: Mapped[int] = mapped_column(Integer, nullable=False,
                                               default=0, server_default="0")

    dashboard: Mapped["Dashboard"] = relationship(back_populates="widgets")

    def __repr__(self) -> str:
        return f"<DashboardWidget id={self.id} code={self.code!r} type={self.widget_type!r}>"
