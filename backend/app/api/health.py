"""Health-check endpoints."""

import logging
import re

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.database import get_db
from app.schemas.health import DatabaseHealthResponse, HealthResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/health", tags=["system"])


def _safe_error(exc: Exception) -> str:
    """
    Turn a database exception into a message that is useful to a developer but
    never leaks credentials.

    A connection URL looks like postgresql+psycopg://user:password@host:5432/db
    and driver errors sometimes echo it back. The substitution below replaces
    everything between "://" and "@" with "***", so any user name and password
    are removed before the text leaves the server.

    PostgreSQL's own "password authentication failed for user X" message still
    names the user, which is deliberate: it is the single most useful clue when
    the connection is misconfigured, and this API is local-only. If this app is
    ever exposed beyond localhost, tighten this to a fixed generic string and
    read the real reason from the server log instead.
    """
    message = str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__
    message = re.sub(r"://[^@/\s]*@", "://***@", message)
    return message[:300]


@router.get("", response_model=HealthResponse)
def health() -> HealthResponse:
    """Liveness check: is the API process running? Does not touch the database."""
    return HealthResponse(status="ok", service=settings.app_name)


@router.get("/db", response_model=DatabaseHealthResponse)
def health_db(db: Session = Depends(get_db)) -> DatabaseHealthResponse:
    """
    Readiness check: can the API actually reach PostgreSQL?

    Runs the cheapest possible round trip and asks the server which database it
    landed in, which also confirms the URL points where you think it does.
    """
    try:
        database_name = db.execute(text("SELECT current_database()")).scalar_one()
    except SQLAlchemyError as exc:
        # The full error (with stack trace) goes to the server log; the client
        # gets the sanitised one-line version.
        logger.exception("Database health check failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "status": "error",
                "database": "unavailable",
                "reason": _safe_error(exc),
            },
        ) from exc

    return DatabaseHealthResponse(status="ok", database=database_name)
