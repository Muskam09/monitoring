"""Shared pytest fixtures for the backend test suite.

This file is loaded automatically by pytest *before* any test module is
imported. It performs two critical jobs:

1. Overrides ``backend.database.engine`` and ``SessionLocal`` so that
   every test runs against an in-memory SQLite database instead of the
   real Postgres instance. We do this BEFORE importing ``models`` so
   that ``models.Base.metadata`` binds to the sqlite engine's metadata.

2. Exposes a ``db_session`` fixture that yields a fresh, isolated DB
   session per test and rolls back / drops tables afterwards.

Why in-memory SQLite + StaticPool?
    - no external service required → tests run on any dev machine / CI
    - ``StaticPool`` makes the single in-memory DB visible across all
      connections opened from the same engine (otherwise each new
      connection would see an empty, independent database).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# ─── Make backend/ importable when pytest is invoked from backend/ ─────
# `pytest -v` is run from backend/, so backend/ itself must be on
# sys.path for `import models` / `import auth` / etc. to resolve.
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# Force a predictable JWT secret for the token-related unit tests.
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-do-not-use-in-production")
os.environ.setdefault("JWT_ALGORITHM", "HS256")
os.environ.setdefault("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "30")

# ─── Swap the real Postgres engine for an in-memory SQLite one ─────────
# We import `database` first (which builds the Postgres engine from the
# env var), then override its `engine` + `SessionLocal` attributes with
# a SQLite-backed pair. All downstream modules (`models`, `auth`, …)
# that `from database import Base, SessionLocal` will pick up the
# replacements because Python modules are singletons.
import database  # noqa: E402

TEST_DATABASE_URL = "sqlite:///:memory:"

test_engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,  # share the one in-memory DB across connections
)
TestSessionLocal = sessionmaker(
    autocommit=False, autoflush=False, bind=test_engine
)

database.engine = test_engine
database.SessionLocal = TestSessionLocal

# Import models AFTER the engine swap so Base.metadata is populated
# while `database.engine` points at SQLite.
import models  # noqa: E402,F401


# ─── Fixtures ──────────────────────────────────────────────────────────
@pytest.fixture(scope="function")
def db_session():
    """Fresh, isolated DB session per test.

    Creates all tables, yields a Session bound to the in-memory SQLite
    engine, then drops every table so the next test starts from a
    guaranteed-clean slate. Function scope keeps tests independent.
    """
    database.Base.metadata.create_all(bind=test_engine)
    session = TestSessionLocal()
    try:
        yield session
    finally:
        session.close()
        database.Base.metadata.drop_all(bind=test_engine)
