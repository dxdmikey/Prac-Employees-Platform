"""
Authentication service.

This is the layer between the HTTP endpoints and the database. Endpoints deal
with requests and responses; this module deals with users and tokens. Keeping
them apart means the login rules can be tested without starting a web server.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import (
    generate_auth_token,
    hash_auth_token,
    verify_password,
)
from app.models.auth_token import AuthToken
from app.models.user import User


class AuthError(Exception):
    """
    Raised when a login attempt fails.

    The endpoint turns this into an HTTP response. Using our own exception here
    keeps FastAPI details out of the service layer.
    """


def get_user_by_username(db: Session, username: str) -> User | None:
    """Look a user up by username. Returns None if there is no such user."""
    return db.scalar(select(User).where(User.username == username))


def authenticate_user(db: Session, username: str, password: str) -> User:
    """
    Check a username and password.

    Returns the User on success and raises AuthError on any failure.

    Note that "no such user" and "wrong password" produce the *same* message.
    Telling an attacker which of the two it was would let them discover valid
    usernames one guess at a time.
    """
    user = get_user_by_username(db, username)

    if user is None or not verify_password(password, user.password_hash):
        raise AuthError("Incorrect username or password")

    if not user.is_active:
        # A deactivated account is a different situation: the credentials were
        # right, so a clear message here helps the person rather than an attacker.
        raise AuthError("This account is inactive")

    return user


def create_auth_token(db: Session, user: User) -> str:
    """
    Start a login session and return the token the client must send back.

    The plaintext token is returned to the caller once and never stored - only
    its hash goes into the database.
    """
    token = generate_auth_token()
    expires_at = datetime.now(timezone.utc) + timedelta(
        minutes=settings.auth_token_expire_minutes
    )

    db.add(
        AuthToken(
            token_hash=hash_auth_token(token),
            user_id=user.id,
            expires_at=expires_at,
        )
    )
    db.commit()
    return token


def get_user_for_token(db: Session, token: str) -> User | None:
    """
    Resolve a token back to its user, or None if it is not usable.

    A token is unusable when it does not exist, has expired, or belongs to an
    account that has since been deactivated. Expired rows are deleted as they
    are encountered, which keeps the table tidy without a scheduled job.
    """
    auth_token = db.scalar(
        select(AuthToken).where(AuthToken.token_hash == hash_auth_token(token))
    )
    if auth_token is None:
        return None

    if auth_token.expires_at <= datetime.now(timezone.utc):
        db.delete(auth_token)
        db.commit()
        return None

    if not auth_token.user.is_active:
        return None

    return auth_token.user


def revoke_token(db: Session, token: str) -> None:
    """
    Log out: delete the token row so it can never be used again.

    This is the advantage of storing sessions in the database. Deleting is
    idempotent - logging out twice is not an error.
    """
    auth_token = db.scalar(
        select(AuthToken).where(AuthToken.token_hash == hash_auth_token(token))
    )
    if auth_token is not None:
        db.delete(auth_token)
        db.commit()
