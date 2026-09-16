"""
Shared test setup.

Every test runs inside a transaction that is rolled back afterwards, so the
tests use your real local database but never leave anything behind.

How that works:
  1. open one connection and start a transaction on it,
  2. give the Session that same connection, with join_transaction_mode set to
     "create_savepoint" so a commit() inside the application only releases a
     savepoint instead of committing for real,
  3. roll the outer transaction back when the test ends.
"""

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from sqlalchemy import select

from app.core.config import settings
from app.core.security import hash_password
from app.db.database import get_db
from app.main import app
from app.metadata.seed import seed_all
from app.models.role import Role
from app.models.user import User

engine = create_engine(settings.database_url)


@pytest.fixture
def db() -> Generator[Session, None, None]:
    """A database session whose changes are always undone."""
    connection = engine.connect()
    transaction = connection.begin()
    # expire_on_commit=False matches SessionLocal in app/db/database.py.
    # Without it the test session reloads every attribute after each commit,
    # which hides staleness bugs that the real application would hit.
    session = Session(
        bind=connection,
        join_transaction_mode="create_savepoint",
        expire_on_commit=False,
    )
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def client(db: Session) -> Generator[TestClient, None, None]:
    """
    A test client whose endpoints use the same rolled-back session.

    dependency_overrides is FastAPI's built-in way to swap a dependency during
    tests - here get_db is replaced so endpoints join the test transaction.
    """

    def override_get_db() -> Generator[Session, None, None]:
        yield db

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def password() -> str:
    """The plaintext password used by the test users below."""
    return "correct-horse-battery"


@pytest.fixture
def active_user(db: Session, password: str) -> User:
    user = User(
        username="testuser",
        email="testuser@example.local",
        employee_code="EMP-TEST-1",
        first_name="Test",
        last_name="User",
        password_hash=hash_password(password),
        is_active=True,
    )
    db.add(user)
    db.commit()
    return user


@pytest.fixture
def inactive_user(db: Session, password: str) -> User:
    user = User(
        username="inactiveuser",
        email="inactive@example.local",
        employee_code="EMP-TEST-2",
        first_name="Inactive",
        last_name="User",
        password_hash=hash_password(password),
        is_active=False,
    )
    db.add(user)
    db.commit()
    return user


# ---------------------------------------------------------------------------
# RBAC fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def seeded(db: Session) -> Session:
    """
    Load the real metadata seed into the test transaction.

    Using the same seed as the application means the tests check the access
    rules you actually run with, not a hand-written imitation of them.
    """
    seed_all(db)
    return db


@pytest.fixture
def make_user(db: Session, password: str):
    """
    Factory fixture: build a user with the given role codes.

    Fixtures cannot take arguments directly, so the fixture returns a function
    the test then calls - the standard pytest pattern for parameterised setup.
    """
    counter = {"n": 0}

    def _make(username: str, role_codes: tuple[str, ...] = (), is_active: bool = True):
        counter["n"] += 1
        user = User(
            username=username,
            email=f"{username}@example.local",
            employee_code=f"EMP-T{counter['n']}",
            first_name=username.capitalize(),
            last_name="Tester",
            password_hash=hash_password(password),
            is_active=is_active,
        )
        db.add(user)
        db.flush()
        for code in role_codes:
            role = db.scalar(select(Role).where(Role.code == code))
            assert role is not None, f"role {code} missing - use the 'seeded' fixture"
            user.roles.append(role)
        db.commit()
        return user

    return _make


@pytest.fixture
def login_headers(client: TestClient, password: str):
    """Log a user in and return the Authorization header to use for them."""

    def _headers(username: str) -> dict[str, str]:
        response = client.post(
            "/api/auth/login", json={"username": username, "password": password}
        )
        assert response.status_code == 200, response.text
        return {"Authorization": f"Bearer {response.json()['access_token']}"}

    return _headers
