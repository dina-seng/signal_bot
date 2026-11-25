"""Promote a Telegram user to admin:  python scripts/seed_admin.py

Reads ADMIN_TELEGRAM_ID from the environment / server/.env. Safe to re-run.
"""

import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import settings
from app.core.database import SessionLocal, init_db
from app.models.user import User


def main() -> None:
    raw = os.environ.get("ADMIN_TELEGRAM_ID") or (
        str(settings.ADMIN_TELEGRAM_ID) if settings.ADMIN_TELEGRAM_ID else ""
    )
    if not raw.strip().lstrip("-").isdigit():
        raise SystemExit(
            "ADMIN_TELEGRAM_ID is not set. Example: ADMIN_TELEGRAM_ID=123456789 python scripts/seed_admin.py"
        )

    telegram_id = int(raw.strip())
    init_db()
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.telegram_id == telegram_id).one_or_none()
        if user is None:
            user = User(id=uuid.uuid4(), telegram_id=telegram_id, is_admin=True)
            db.add(user)
            action = "created"
        else:
            user.is_admin = True
            action = "updated"
        db.commit()
        print(f"Admin Telegram user {telegram_id} {action} (id={user.id}).")
    finally:
        db.close()


if __name__ == "__main__":
    main()
