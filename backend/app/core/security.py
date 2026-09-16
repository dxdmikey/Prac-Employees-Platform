"""
Security helpers: password hashing and login-token generation.

This module deliberately knows nothing about the database or about FastAPI.
It only turns strings into other strings, which makes it easy to read, easy to
test, and reusable from anywhere (API endpoints, scripts, future services).
"""

import hashlib
import secrets

import bcrypt

# bcrypt refuses passwords longer than 72 bytes, so we reject them up front
# with a clear message instead of letting the library raise a confusing error.
MAX_PASSWORD_BYTES = 72


def hash_password(plain_password: str) -> str:
    """
    Turn a plaintext password into a bcrypt hash that is safe to store.

    bcrypt generates a random "salt" for every call, so hashing the same
    password twice produces two different strings. The salt is stored inside
    the resulting hash, which is why verify_password() needs no separate salt.
    """
    password_bytes = plain_password.encode("utf-8")
    if len(password_bytes) > MAX_PASSWORD_BYTES:
        raise ValueError(
            f"Password is too long: bcrypt accepts at most {MAX_PASSWORD_BYTES} bytes."
        )
    return bcrypt.hashpw(password_bytes, bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, password_hash: str) -> bool:
    """
    Check a plaintext password against a stored bcrypt hash.

    A hash cannot be reversed, so this works the other way round: bcrypt
    re-hashes the candidate password using the salt embedded in the stored
    hash and compares the results in constant time.
    """
    password_bytes = plain_password.encode("utf-8")
    if len(password_bytes) > MAX_PASSWORD_BYTES:
        return False
    try:
        return bcrypt.checkpw(password_bytes, password_hash.encode("utf-8"))
    except ValueError:
        # Raised when the stored value is not a valid bcrypt hash (for example
        # a row created by hand). Treat it as "wrong password", never a crash.
        return False


def generate_auth_token() -> str:
    """
    Create a new random login token.

    token_urlsafe(32) returns 32 bytes of cryptographically secure randomness
    as text. It is far too large to guess, and unlike a JWT it carries no
    information at all - it is just a random string that the database maps
    back to a user.
    """
    return secrets.token_urlsafe(32)


def hash_auth_token(token: str) -> str:
    """
    Hash a login token for storage.

    A token is a temporary password, so we store only its fingerprint. If
    someone ever reads the auth_tokens table they still cannot log in as
    anybody, because the original token cannot be recovered from the hash.

    Plain SHA-256 is right here (and bcrypt would be wrong): tokens are long
    random strings, not human-chosen passwords, so there is nothing to brute
    force, and lookups on every request must stay fast.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
