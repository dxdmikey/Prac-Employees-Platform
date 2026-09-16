r"""
Development helper: load the starter metadata (roles, permissions, the eight
applications, their screens, and the role mappings between them).

    cd backend
    .\.venv\Scripts\Activate.ps1
    python scripts/seed_metadata.py

Safe to run as often as you like - everything is matched by `code`, so a second
run inserts nothing. The actual data lives in app/metadata/seed.py; edit that
file and re-run this script to apply changes.

Run scripts/create_admin_user.py first: this script grants SUPER_ADMIN to the
"admin" user, but does not create it and never handles passwords.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.db.database import SessionLocal  # noqa: E402
from app.metadata.seed import ADMIN_USERNAME, seed_all  # noqa: E402
from app.models.user import User  # noqa: E402


def main() -> None:
    db = SessionLocal()
    try:
        admin_exists = db.scalar(
            select(User).where(User.username == ADMIN_USERNAME)
        ) is not None

        created = seed_all(db)

        print("Metadata seed complete. Newly created:")
        for name, count in created.items():
            print(f"  {name:<12} {count}")

        if not admin_exists:
            print(
                f"\nNote: no '{ADMIN_USERNAME}' user found, so no role was granted.\n"
                "Run 'python scripts/create_admin_user.py' and then re-run this "
                "script to make that user a Super Admin."
            )
    finally:
        db.close()


if __name__ == "__main__":
    main()
