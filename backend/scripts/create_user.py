r"""
Development helper: create an ordinary user with some roles.

Useful for seeing RBAC from the other side - log in as an Employee and watch
the menu shrink. Without a second user, the admin screen has nobody to manage.

    cd backend
    .\.venv\Scripts\Activate.ps1
    python scripts/create_user.py jane EMPLOYEE
    python scripts/create_user.py priya HR MANAGER

The password comes from the USER_PASSWORD environment variable, or from a
hidden prompt if that is not set. Only the bcrypt hash is stored, and no
password is written in this file. Re-running for an existing username resets
that user's password and replaces their roles.
"""

import getpass
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.core.security import MAX_PASSWORD_BYTES, hash_password  # noqa: E402
from app.db.database import SessionLocal  # noqa: E402
from app.models.role import Role  # noqa: E402
from app.models.user import User  # noqa: E402

MIN_PASSWORD_LENGTH = 8


def read_password() -> str:
    password = os.getenv("USER_PASSWORD")
    if not password:
        password = getpass.getpass("Password for this user: ")
        if password != getpass.getpass("Repeat the password: "):
            sys.exit("The two passwords do not match. Nothing was changed.")

    if len(password) < MIN_PASSWORD_LENGTH:
        sys.exit(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        sys.exit(f"Password exceeds bcrypt's {MAX_PASSWORD_BYTES}-byte limit.")
    return password


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit("Usage: python scripts/create_user.py <username> [ROLE_CODE ...]")

    username = sys.argv[1].strip().lower()
    role_codes = [code.strip().upper() for code in sys.argv[2:]]
    password = read_password()

    db = SessionLocal()
    try:
        roles = []
        for code in role_codes:
            role = db.scalar(select(Role).where(Role.code == code))
            if role is None:
                sys.exit(
                    f"No role with code {code}. "
                    "Run 'python scripts/seed_metadata.py' first."
                )
            roles.append(role)

        user = db.scalar(select(User).where(User.username == username))
        if user is None:
            user = User(
                username=username,
                email=f"{username}@example.local",
                employee_code=f"EMP-{username.upper()}",
                first_name=username.capitalize(),
                last_name="Demo",
                password_hash=hash_password(password),
                is_active=True,
            )
            db.add(user)
            action = "created"
        else:
            user.password_hash = hash_password(password)
            user.is_active = True
            action = "updated"

        user.roles = roles
        db.commit()

        granted = ", ".join(role.code for role in roles) or "(no roles)"
        print(f"User {action}: {username} -> {granted}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
