"""Tests for the authentication endpoints."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.user import User


def login(client: TestClient, username: str, password: str):
    return client.post(
        "/api/auth/login", json={"username": username, "password": password}
    )


# --- login ------------------------------------------------------------------


def test_successful_login_returns_a_token_and_the_user(
    client: TestClient, active_user: User, password: str
) -> None:
    response = login(client, active_user.username, password)

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert len(body["access_token"]) > 20
    assert body["user"]["username"] == active_user.username
    assert body["user"]["is_active"] is True
    # The hash must never travel to the client.
    assert "password_hash" not in body["user"]


def test_login_with_wrong_password_is_rejected(
    client: TestClient, active_user: User
) -> None:
    response = login(client, active_user.username, "definitely-wrong")

    assert response.status_code == 401
    assert response.json()["detail"] == "Incorrect username or password"


def test_login_with_nonexistent_user_is_rejected(client: TestClient) -> None:
    response = login(client, "nobody", "any-password")

    assert response.status_code == 401
    # Identical message to the wrong-password case, so an attacker cannot
    # discover which usernames exist.
    assert response.json()["detail"] == "Incorrect username or password"


def test_inactive_user_cannot_log_in(
    client: TestClient, inactive_user: User, password: str
) -> None:
    response = login(client, inactive_user.username, password)

    assert response.status_code == 401
    assert response.json()["detail"] == "This account is inactive"


def test_login_requires_both_fields(client: TestClient) -> None:
    response = client.post("/api/auth/login", json={"username": "admin"})
    assert response.status_code == 422  # Pydantic rejected the body


# --- /api/auth/me -----------------------------------------------------------


def test_me_without_a_token_is_rejected(client: TestClient) -> None:
    response = client.get("/api/auth/me")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_me_with_a_nonsense_token_is_rejected(client: TestClient) -> None:
    response = client.get(
        "/api/auth/me", headers={"Authorization": "Bearer made-up-token"}
    )
    assert response.status_code == 401


def test_me_with_a_valid_token_returns_the_user(
    client: TestClient, active_user: User, password: str
) -> None:
    token = login(client, active_user.username, password).json()["access_token"]

    response = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "id": active_user.id,
        "username": "testuser",
        "email": "testuser@example.local",
        "first_name": "Test",
        "last_name": "User",
        "is_active": True,
    }
    assert "password_hash" not in body


def test_token_stops_working_when_the_user_is_deactivated(
    client: TestClient, active_user: User, password: str, db: Session
) -> None:
    token = login(client, active_user.username, password).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/auth/me", headers=headers).status_code == 200

    active_user.is_active = False
    db.commit()

    assert client.get("/api/auth/me", headers=headers).status_code == 401


# --- logout -----------------------------------------------------------------


def test_logout_makes_the_token_unusable(
    client: TestClient, active_user: User, password: str
) -> None:
    token = login(client, active_user.username, password).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    logout = client.post("/api/auth/logout", headers=headers)
    assert logout.status_code == 200
    assert logout.json() == {"message": "Logged out"}

    # The same token is now dead.
    assert client.get("/api/auth/me", headers=headers).status_code == 401


def test_logout_without_a_token_is_rejected(client: TestClient) -> None:
    assert client.post("/api/auth/logout").status_code == 401


def test_logging_in_twice_gives_two_independent_tokens(
    client: TestClient, active_user: User, password: str
) -> None:
    first = login(client, active_user.username, password).json()["access_token"]
    second = login(client, active_user.username, password).json()["access_token"]
    assert first != second

    # Logging out of one session must not end the other (e.g. phone vs laptop).
    client.post("/api/auth/logout", headers={"Authorization": f"Bearer {first}"})

    assert client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {first}"}
    ).status_code == 401
    assert client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {second}"}
    ).status_code == 200
