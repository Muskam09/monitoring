"""Host + HostAccess persistence."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

import models


class HostRepository:
    """Repository for the ``Host`` aggregate, including RBAC grants."""

    def __init__(self, db: Session):
        self.db = db

    # ─── Lookups ───────────────────────────────────────────────────────
    def get_by_id(self, host_id: int) -> Optional[models.Host]:
        return self.db.query(models.Host).filter(models.Host.id == host_id).first()

    def get_by_name(self, name: str) -> Optional[models.Host]:
        return self.db.query(models.Host).filter(models.Host.name == name).first()

    def get_by_api_token(self, token: str) -> Optional[models.Host]:
        return (
            self.db.query(models.Host)
            .filter(models.Host.api_token == token)
            .first()
        )

    def list_by_ids(self, host_ids: set[int]) -> list[models.Host]:
        if not host_ids:
            return []
        return (
            self.db.query(models.Host)
            .filter(models.Host.id.in_(host_ids))
            .order_by(models.Host.id.asc())
            .all()
        )

    # ─── RBAC helpers ──────────────────────────────────────────────────
    def visible_host_ids(self, user: models.User) -> set[int]:
        if user.is_admin:
            return {h[0] for h in self.db.query(models.Host.id).all()}
        owned = {
            h[0]
            for h in self.db.query(models.Host.id)
            .filter(models.Host.owner_id == user.id)
            .all()
        }
        shared = {
            h[0]
            for h in self.db.query(models.HostAccess.host_id)
            .filter(models.HostAccess.user_id == user.id)
            .all()
        }
        return owned | shared

    def owned_ids(self, user_id: int) -> list[int]:
        return [
            h[0]
            for h in self.db.query(models.Host.id)
            .filter(models.Host.owner_id == user_id)
            .all()
        ]

    def has_access(self, host_id: int, user_id: int) -> bool:
        return (
            self.db.query(models.HostAccess)
            .filter(models.HostAccess.host_id == host_id)
            .filter(models.HostAccess.user_id == user_id)
            .first()
            is not None
        )

    def list_access_grants(self, host_id: int) -> list[models.HostAccess]:
        return (
            self.db.query(models.HostAccess)
            .filter(models.HostAccess.host_id == host_id)
            .all()
        )

    def get_access_grant(
        self, host_id: int, user_id: int
    ) -> Optional[models.HostAccess]:
        return (
            self.db.query(models.HostAccess)
            .filter(models.HostAccess.host_id == host_id)
            .filter(models.HostAccess.user_id == user_id)
            .first()
        )

    def shared_host_ids(self, user_id: int) -> list[int]:
        return [
            h[0]
            for h in self.db.query(models.HostAccess.host_id)
            .filter(models.HostAccess.user_id == user_id)
            .all()
        ]

    # ─── Mutations ─────────────────────────────────────────────────────
    def add(self, host: models.Host) -> models.Host:
        self.db.add(host)
        self.db.commit()
        self.db.refresh(host)
        return host

    def delete(self, host: models.Host) -> None:
        self.db.delete(host)
        self.db.commit()

    def add_access_grant(
        self, *, host_id: int, user_id: int, granted_by_id: int
    ) -> models.HostAccess:
        grant = models.HostAccess(
            host_id=host_id, user_id=user_id, granted_by_id=granted_by_id
        )
        self.db.add(grant)
        self.db.commit()
        self.db.refresh(grant)
        return grant

    def delete_access_grant(self, grant: models.HostAccess) -> None:
        self.db.delete(grant)
        self.db.commit()

    def mark_stale_offline(self, *, offline_after_seconds: int) -> None:
        """Flip hosts that haven't checked in recently to is_online=False."""
        cutoff = datetime.now(timezone.utc) - timedelta(
            seconds=offline_after_seconds
        )
        (
            self.db.query(models.Host)
            .filter(models.Host.last_seen_at != None)  # noqa: E711
            .filter(models.Host.last_seen_at < cutoff)
            .filter(models.Host.is_online.is_(True))
            .update({models.Host.is_online: False}, synchronize_session=False)
        )
        self.db.commit()

    def touch_heartbeat(
        self,
        host: models.Host,
        *,
        os_info: Optional[str] = None,
        uptime_seconds: Optional[int] = None,
    ) -> None:
        """Called on every telemetry POST: mark online + stamp last_seen_at
        + one-time fill of OS / uptime."""
        host.is_online = True  # type: ignore[assignment]
        host.last_seen_at = datetime.now(timezone.utc)
        if os_info and not host.os_info:
            host.os_info = os_info
        if uptime_seconds is not None:
            host.uptime_seconds = uptime_seconds
        self.db.commit()
