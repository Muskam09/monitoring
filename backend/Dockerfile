FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# entrypoint.sh runs `alembic upgrade head` before launching uvicorn,
# so schema drift (e.g. missing hosts.owner_id) can never recur on
# container start. `chmod +x` is explicit because Windows bind-mounts
# don't preserve POSIX execute bits.
RUN chmod +x /app/entrypoint.sh

ENTRYPOINT ["/app/entrypoint.sh"]