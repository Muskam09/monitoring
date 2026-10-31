"""Promote an existing user to admin (sets is_admin=True, is_active=True).

Usage (inside the backend container):

    docker compose exec backend python make_admin.py <username>

If the username does not exist, exits with code 1.
"""
import sys

from database import SessionLocal
import models


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: python make_admin.py <username>")
        return 2
    username = sys.argv[1]
    db = SessionLocal()
    try:
        u = db.query(models.User).filter(models.User.username == username).first()
        if not u:
            print(f"[make_admin] user {username!r} not found")
            return 1
        u.is_admin = True
        u.is_active = True
        u.is_locked = False
        db.commit()
        print(
            f"[make_admin] {u.username} ({u.email}) — "
            f"is_admin=True, is_active=True, is_locked=False"
        )
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
