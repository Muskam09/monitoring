# Database migrations (Alembic)

The backend uses **Alembic** for schema migrations. The `main.py` entrypoint still
runs `Base.metadata.create_all()` as an MVP convenience, but once the first
migration is generated the recommended workflow is:

```bash
# Inside the backend container (or venv):
cd backend

# Generate a new migration after editing models.py
alembic revision --autogenerate -m "describe change"

# Apply pending migrations
alembic upgrade head

# Roll back one revision
alembic downgrade -1
```

The DB URL is read from the `DATABASE_URL` environment variable, so Alembic
hits the same database as the running app.

The `versions/` directory holds generated migration scripts and is tracked in
git. It is intentionally empty at project kickoff.
