"""
AuthToken model - one row per active login.

HTTP is stateless: the server forgets everything between requests. So after a
successful login we hand the browser a random token, and store a fingerprint
of it here next to the user id. When the browser sends that token back, this
table is how the backend answers "who is this?".

Logging out is then simply deleting the row, which is why the token lives in
the database rather than inside a self-contained JWT: a JWT stays valid until
it expires and cannot be taken back.
"""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.user import User


class AuthToken(Base):
    __tablename__ = "auth_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)

    # The SHA-256 fingerprint of the token, never the token itself.
    # unique=True gives us the index used to look a token up on every request.
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Logins do not last forever. Anything past this moment is refused.
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped["User"] = relationship()

    def __repr__(self) -> str:
        return f"<AuthToken id={self.id} user_id={self.user_id}>"
