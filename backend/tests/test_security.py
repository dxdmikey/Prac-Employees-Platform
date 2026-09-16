"""Tests for the password hashing helpers (no database involved)."""

from app.core.security import (
    generate_auth_token,
    hash_auth_token,
    hash_password,
    verify_password,
)


def test_correct_password_verifies() -> None:
    hashed = hash_password("s3cret-password")
    assert verify_password("s3cret-password", hashed) is True


def test_incorrect_password_is_rejected() -> None:
    hashed = hash_password("s3cret-password")
    assert verify_password("wrong-password", hashed) is False


def test_hash_is_not_the_plaintext() -> None:
    hashed = hash_password("s3cret-password")
    assert "s3cret-password" not in hashed
    assert hashed.startswith("$2b$")  # the bcrypt marker


def test_same_password_hashes_differently_each_time() -> None:
    """Because bcrypt salts every hash, two hashes of one password differ."""
    first = hash_password("s3cret-password")
    second = hash_password("s3cret-password")
    assert first != second
    assert verify_password("s3cret-password", first)
    assert verify_password("s3cret-password", second)


def test_verify_password_survives_a_corrupt_hash() -> None:
    assert verify_password("anything", "not-a-bcrypt-hash") is False


def test_tokens_are_unique_and_hashed_consistently() -> None:
    token = generate_auth_token()
    assert token != generate_auth_token()
    assert hash_auth_token(token) == hash_auth_token(token)
    assert token not in hash_auth_token(token)
