"""User persistence — centralises every ``db.query(User)`` call."""
from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

import models


class UserRepository:
    """Repository for the ``User`` aggregate.

    Routes receive this via FastAPI ``Depends`` and never touch
    ``db.query(models.User)`` directly.
    """

    def __init__(self, db: Session):
        self.db = db

    # ─── Lookups ───────────────────────────────────────────────────────
    def get_by_id(self, user_id: int) -> Optional[models.User]:
        return self.db.query(models.User).filter(models.User.id == user_id).first()

    def get_by_username(self, username: str) -> Optional[models.User]:
        return (
            self.db.query(models.User)
            .filter(models.User.username == username)
            .first()
        )

    def get_by_email(self, email: str) -> Optional[models.User]:
        return (
            self.db.query(models.User)
            .filter(models.User.email == email)
            .first()
        )

    def find_by_email_or_username(self, identifier: str) -> Optional[models.User]:
        """Accept either email or username. Username match is case-sensitive,
        email match is case-insensitive (mirrors the legacy helper in main.py)."""
        ident = (identifier or "").strip()
        if not ident:
            return None
        u = self.get_by_username(ident)
        if u:
            return u
        return (
            self.db.query(models.User)
            .filter(models.User.email.ilike(ident))
            .first()
        )

    def list_all(self) -> list[models.User]:
        return self.db.query(models.User).order_by(models.User.id.asc()).all()

    # ─── Mutations ─────────────────────────────────────────────────────
    def add(self, user: models.User) -> models.User:
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user

    def save(self) -> None:
        """Commit pending in-flight changes on a tracked instance."""
        self.db.commit()

    def reset_failed_attempts(self, user: models.User) -> None:
        user.failed_login_attempts = 0
        user.locked_until = None
        self.db.commit()

    def bump_failed_attempt(
        self, user: models.User, *, max_attempts: int, lock_minutes: int
    ) -> None:
        """Increment the brute-force counter and apply a temporary soft-lock
        once the threshold is crossed."""
        from datetime import datetime, timedelta, timezone

        user.failed_login_attempts = (user.failed_login_attempts or 0) + 1
        if user.failed_login_attempts >= max_attempts:
            user.locked_until = datetime.now(timezone.utc) + timedelta(
                minutes=lock_minutes
            )
        self.db.commit()
