#!/bin/sh
# Container entrypoint.
#
# 1. Apply any pending Alembic migrations so the live DB schema always
#    matches the ORM models (e.g. adds `hosts.owner_id` on upgrade).
# 2. Hand off to uvicorn.
#
# The `stamp 0001_baseline` step marks the baseline revision as applied
# WITHOUT re-running it on databases that were originally initialised by
# `Base.metadata.create_all()` before Alembic was wired in. It is a no-op
# once alembic_version already contains 0001_baseline or later.
set -e

echo "[entrypoint] Waiting for Postgres…"
# Simple wait-loop. Postgres healthcheck in compose covers most cases
# but a best-effort ping here guards against race conditions on cold boot.
python - <<'PY'
import os, time, sys
from sqlalchemy import create_engine, text
url = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://postgres:postgres@db:5432/devops_dashboard",
)
for i in range(30):
    try:
        with create_engine(url).connect() as c:
            c.execute(text("SELECT 1"))
        print(f"[entrypoint] Postgres reachable (attempt {i+1})")
        sys.exit(0)
    except Exception as e:
        print(f"[entrypoint] Postgres not ready yet ({e.__class__.__name__}); retrying…")
        time.sleep(1)
print("[entrypoint] Postgres never came up — aborting", file=sys.stderr)
sys.exit(1)
PY

echo "[entrypoint] Baselining alembic_version (no-op if already stamped)…"
# If alembic_version table is empty (legacy DB that was built by
# create_all() before Alembic existed), stamp it to the baseline so the
# subsequent `upgrade head` only applies NEW migrations and doesn't try
# to CREATE TABLE on existing tables. Each check runs in its OWN
# transaction so a failed query (e.g. missing alembic_version) doesn't
# poison the next one.
python - <<'PY'
import os
from sqlalchemy import create_engine, text
url = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://postgres:postgres@db:5432/devops_dashboard",
)
engine = create_engine(url)

# Check 1: is alembic_version already populated?
row = None
try:
    with engine.connect() as c:
        row = c.execute(
            text("SELECT version_num FROM alembic_version LIMIT 1")
        ).first()
except Exception:
    row = None  # table doesn't exist yet (fresh DB OR legacy DB)

# Check 2 (separate transaction): does the pre-Alembic schema exist?
has_hosts = False
try:
    with engine.connect() as c:
        has_hosts = bool(c.execute(
            text("SELECT to_regclass('public.hosts') IS NOT NULL")
        ).scalar())
except Exception:
    has_hosts = False

if row is None and has_hosts:
    # Legacy DB → stamp baseline so 0002 is the only migration applied.
    print("[entrypoint] Legacy DB detected — stamping 0001_baseline")
    os.system("alembic stamp 0001_baseline")
else:
    print(f"[entrypoint] alembic_version row={row} has_hosts={has_hosts} — no stamp needed")
PY

echo "[entrypoint] Applying Alembic migrations…"
alembic upgrade head

echo "[entrypoint] Launching application…"
# Compose may pass its own `command:` (e.g. uvicorn with --reload for dev).
# When it does, args land in "$@" — honor them verbatim. Otherwise fall
# back to a sensible default uvicorn invocation.
if [ "$#" -gt 0 ]; then
    exec "$@"
else
    exec uvicorn main:app --host 0.0.0.0 --port 8000
fi
