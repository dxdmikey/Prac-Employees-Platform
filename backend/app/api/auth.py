"""Authentication endpoints: login, who-am-I, and logout."""

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.database import get_db
from app.models.user import User
from app.schemas.auth import (
    LoginRequest,
    LoginResponse,
    MessageResponse,
    UserResponse,
)
from app.services import auth_service
from app.services.auth_service import AuthError

router = APIRouter(prefix="/api/auth", tags=["auth"])

bearer_scheme = HTTPBearer(auto_error=False)


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> LoginResponse:
    """
    Exchange a username and password for a token.

    On success the client stores the token and sends it back on every later
    request as "Authorization: Bearer <token>".
    """
    try:
        user = auth_service.authenticate_user(db, payload.username, payload.password)
    except AuthError as exc:
        # 401 means "we do not know who you are". The message deliberately does
        # not say whether it was the username or the password that was wrong.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    token = auth_service.create_auth_token(db, user)
    return LoginResponse(access_token=token, user=UserResponse.model_validate(user))


@router.get("/me", response_model=UserResponse)
def read_current_user(current_user: User = Depends(get_current_user)) -> UserResponse:
    """
    Return the signed-in user.

    This endpoint has no logic of its own - get_current_user has already done
    the work, and it either produced a User or raised 401. The response schema
    has no password_hash field, so the hash cannot be returned.
    """
    return UserResponse.model_validate(current_user)


@router.post("/logout", response_model=MessageResponse)
def logout(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    # Requiring a valid user means an expired or bogus token gets a 401 rather
    # than a cheerful "logged out".
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MessageResponse:
    """Delete the caller's token so it stops working immediately."""
    if credentials is not None:
        auth_service.revoke_token(db, credentials.credentials)
    return MessageResponse(message="Logged out")
