"""
Database engine and session handling.

Three pieces, in the order they are created:

1. engine       - manages the pool of connections to PostgreSQL.
2. SessionLocal - a factory that produces Session objects.
3. get_db()     - a FastAPI dependency that hands one Session to a request
                  and always closes it afterwards.
"""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

# The engine is created once for the whole application.
# pool_pre_ping checks a pooled connection is still alive before reusing it,
# which avoids "server closed the connection unexpectedly" errors after idle
# periods - a common annoyance during local development.
engine = create_engine(
    settings.database_url,
    echo=settings.db_echo,
    pool_pre_ping=True,
)

# A Session is a single "unit of work": it tracks the objects you load and
# change, and writes them out when you commit.
SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)


def get_db() -> Generator[Session, None, None]:
    """
    FastAPI dependency that provides a database session per request.

    Usage in an endpoint:
        def endpoint(db: Session = Depends(get_db)): ...

    The "finally" block guarantees the session is closed and its connection
    returned to the pool, even if the endpoint raises.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
