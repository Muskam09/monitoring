"""Integration tests — exercise the SQLAlchemy ORM against a real
(in-memory SQLite) database using the ``db_session`` fixture from
``conftest.py``.

Covers:
  • IT-001: create & persist a models.User
  • IT-002: create a models.Host and bind an API token
  • IT-003: persist HostMetric rows and retrieve the latest by host_id
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

import models
from auth import get_password_hash


# ────────────────────────────────────────────────────────────────────────
# IT-001 — create a user via ORM and verify persistence
# ────────────────────────────────────────────────────────────────────────
def test_it001_create_user_persists_to_db(db_session):
    """A new models.User row is written and re-queryable with the
    expected field values and server-side defaults."""
    user = models.User(
        username="alice",
        email="alice@example.com",
        password_hash=get_password_hash("Str0ng!Passw0rd"),
        role=models.RoleEnum.editor,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    # Primary key must be assigned by the DB.
    assert user.id is not None

    # Round-trip the row to prove it hit the database, not just ORM memory.
    fetched = (
        db_session.query(models.User)
        .filter(models.User.username == "alice")
        .one()
    )
    assert fetched.id == user.id
    assert fetched.email == "alice@example.com"
    assert fetched.role == models.RoleEnum.editor
    assert fetched.is_active is True
    # Server-side defaults from models.User definition.
    assert fetched.is_admin is False
    assert fetched.is_locked is False
    assert fetched.is_2fa_enabled is False
    assert fetched.failed_login_attempts == 0
    assert fetched.password_hash != "Str0ng!Passw0rd"  # must be hashed, not plain


# ────────────────────────────────────────────────────────────────────────
# IT-002 — create a host and bind an API token
# ────────────────────────────────────────────────────────────────────────
def test_it002_create_host_with_api_token(db_session):
    """A new models.Host row persists with its API token, and the token
    can be used to look the host back up (the lookup path used by
    POST /api/telemetry in main.py)."""
    # Owner first — hosts may have an owner_id FK.
    owner = models.User(
        username="bob",
        email="bob@example.com",
        password_hash=get_password_hash("Str0ng!Passw0rd"),
        is_active=True,
    )
    db_session.add(owner)
    db_session.commit()
    db_session.refresh(owner)

    api_token = secrets.token_urlsafe(32)
    host = models.Host(
        name="prod-web-01",
        ip_address="10.0.0.5",
        port=45876,
        api_token=api_token,
        public_key="ssh-ed25519 AAAA… bob@dashboard",
        owner_id=owner.id,
    )
    db_session.add(host)
    db_session.commit()
    db_session.refresh(host)

    assert host.id is not None
    assert host.api_token == api_token
    # Default `is_online` must be False until the agent first checks in.
    assert host.is_online is False
    assert host.created_at is not None

    # Reverse lookup by API token — this is literally the path the
    # /api/telemetry endpoint uses to authenticate the agent.
    by_token = (
        db_session.query(models.Host)
        .filter(models.Host.api_token == api_token)
        .one()
    )
    assert by_token.id == host.id
    assert by_token.name == "prod-web-01"
    assert by_token.owner_id == owner.id


# ────────────────────────────────────────────────────────────────────────
# IT-003 — persist HostMetric rows and fetch the latest by host_id
# ────────────────────────────────────────────────────────────────────────
def test_it003_host_metrics_latest_by_host_id(db_session):
    """Insert several HostMetric rows for a host and verify the
    "latest N for a host" query (used by GET /api/hosts/{id}/metrics)
    returns them in correct, descending-timestamp order."""
    # Minimal host — no owner needed for the metric path.
    host = models.Host(
        name="metrics-host",
        ip_address="10.0.0.6",
        api_token=secrets.token_urlsafe(32),
    )
    db_session.add(host)
    db_session.commit()
    db_session.refresh(host)

    # Three metric snapshots, spread 15 s apart, like the real agent.
    base_ts = datetime.now(timezone.utc)
    samples = [
        # (cpu, ram, disk, offset_seconds)
        (10.0, 20.0, 30.0, -30),  # oldest
        (15.0, 25.0, 31.0, -15),
        (22.5, 40.0, 32.0, 0),    # newest
    ]
    for cpu, ram, disk, offset in samples:
        db_session.add(
            models.HostMetric(
                host_id=host.id,
                cpu_percent=cpu,
                ram_percent=ram,
                disk_percent=disk,
                timestamp=base_ts + timedelta(seconds=offset),
            )
        )
    db_session.commit()

    # Sanity: all three rows persisted against the right host.
    total = (
        db_session.query(models.HostMetric)
        .filter(models.HostMetric.host_id == host.id)
        .count()
    )
    assert total == 3

    # "Latest N" query — matches the ORM shape used in main.py
    # (desc timestamp, limit N).
    latest_two = (
        db_session.query(models.HostMetric)
        .filter(models.HostMetric.host_id == host.id)
        .order_by(models.HostMetric.timestamp.desc())
        .limit(2)
        .all()
    )
    assert len(latest_two) == 2
    # Newest first.
    assert latest_two[0].cpu_percent == 22.5
    assert latest_two[1].cpu_percent == 15.0
    # And the ordering is strictly descending.
    assert latest_two[0].timestamp >= latest_two[1].timestamp
