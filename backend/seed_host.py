"""One-shot seed script: create the first monitored host so the agent can connect.

Usage (inside the backend container):

    docker compose exec backend python seed_host.py local-dev

The script reads AGENT_API_TOKEN from the environment and attaches it to a
host record with the given name. Running it again on the same name is a no-op.
"""
import os
import sys

from database import SessionLocal
import models


def main() -> int:
    name = sys.argv[1] if len(sys.argv) > 1 else "local-dev"
    token = os.getenv("AGENT_API_TOKEN")
    if not token:
        print("[seed] AGENT_API_TOKEN is not set in the environment.")
        return 2

    db = SessionLocal()
    try:
        existing = db.query(models.Host).filter(models.Host.name == name).first()
        if existing:
            # Keep the stored token in sync with whatever is in the env.
            existing.api_token = token  # type: ignore[assignment]
            db.commit()
            print(f"[seed] Host '{name}' already existed — token refreshed.")
            return 0
        host = models.Host(name=name, api_token=token, is_online=False)
        db.add(host)
        db.commit()
        print(f"[seed] Host '{name}' created with the configured AGENT_API_TOKEN.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
