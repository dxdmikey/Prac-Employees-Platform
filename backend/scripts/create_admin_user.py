r"""
Development helper: create (or update) the local admin user.

This is a convenience for local learning, NOT production seed infrastructure.
Run it once after setting up the database:

    Windows PowerShell:
        cd backend
        .\.venv\Scripts\Activate.ps1
        python scripts/create_admin_user.py

The password is never written in this file. It comes from either:

  1. the ADMIN_PASSWORD environment variable, or
  2. a hidden prompt, if that variable is not set.

Whichever way it arrives, only the bcrypt hash is stored in the database.
"""

import getpass
import os
import sys
from pathlib import Path

# Allow "python scripts/create_admin_user.py" to import the app package.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.security import MAX_PASSWORD_BYTES, hash_password  # noqa: E402
from app.db.database import SessionLocal  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services.auth_service import get_user_by_username  # noqa: E402

ADMIN_USERNAME = "admin"
ADMIN_EMAIL = "admin@example.local"
ADMIN_FIRST_NAME = "Platform"
ADMIN_LAST_NAME = "Admin"
ADMIN_EMPLOYEE_CODE = "EMP-ADMIN"

MIN_PASSWORD_LENGTH = 8


def read_password() -> str:
    """Take the password from the environment, or ask for it without echoing."""
    password = os.getenv("ADMIN_PASSWORD")
    source = "the ADMIN_PASSWORD environment variable"

    if not password:
        source = "the prompt"
        password = getpass.getpass("Password for the admin user: ")
        confirmation = getpass.getpass("Repeat the password: ")
        if password != confirmation:
            sys.exit("The two passwords do not match. Nothing was changed.")

    if len(password) < MIN_PASSWORD_LENGTH:
        sys.exit(
            f"Password from {source} is too short "
            f"(minimum {MIN_PASSWORD_LENGTH} characters). Nothing was changed."
        )
    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        sys.exit(
            f"Password from {source} is longer than bcrypt's "
            f"{MAX_PASSWORD_BYTES}-byte limit. Nothing was changed."
        )
    return password


def main() -> None:
    password = read_password()
    db = SessionLocal()
    try:
        user = get_user_by_username(db, ADMIN_USERNAME)

        if user is None:
            user = User(
                username=ADMIN_USERNAME,
                email=ADMIN_EMAIL,
                employee_code=ADMIN_EMPLOYEE_CODE,
                first_name=ADMIN_FIRST_NAME,
                last_name=ADMIN_LAST_NAME,
                password_hash=hash_password(password),
                is_active=True,
            )
            db.add(user)
            action = "created"
        else:
            # Re-running the script resets the password, which is handy when
            # you forget what you typed the first time.
            user.password_hash = hash_password(password)
            user.is_active = True
            action = "updated"

        db.commit()
        print(f"Admin user {action}: username={ADMIN_USERNAME} email={ADMIN_EMAIL}")
        print("Only the bcrypt hash was stored - the password itself is not saved.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
