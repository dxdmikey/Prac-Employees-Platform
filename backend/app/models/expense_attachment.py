"""ExpenseAttachment model - the receipt behind a claim."""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.expense import Expense


class ExpenseAttachment(Base):
    """
    Metadata about one uploaded receipt. The bytes live on disk, not here.

    **Why two names.** `file_name` is what the person called the file and is
    only ever displayed. `stored_name` is what the server called it - a
    generated identifier plus an extension - and is the only thing used to
    build a path.

    That split is the security boundary. A browser can upload something called
    `../../../../etc/passwd` or `report.pdf\\x00.exe`, and if the server built
    a path from that string it would be writing wherever the attacker chose.
    Generating the stored name server-side means the client's string never
    reaches the filesystem, and the client never learns the real path either -
    downloads are addressed by attachment id and the file is streamed back
    after the usual scope check.

    There is no `updated_at`: a receipt is uploaded or deleted, never edited.
    """

    __tablename__ = "expense_attachments"

    id: Mapped[int] = mapped_column(primary_key=True)

    # CASCADE: a receipt has no meaning without its claim.
    expense_id: Mapped[int] = mapped_column(
        ForeignKey("expenses.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # The original name, for display only. Never used to build a path.
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)

    # The server's name for the file on disk: a UUID hex plus an extension
    # taken from the validated content type, so it contains nothing a caller
    # supplied. Unique because it is generated, and indexed because it is how
    # a download finds the bytes.
    stored_name: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False
    )

    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    expense: Mapped["Expense"] = relationship(back_populates="attachments")

    def __repr__(self) -> str:
        return f"<ExpenseAttachment id={self.id} expense_id={self.expense_id}>"
