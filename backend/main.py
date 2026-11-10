import logging
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import auth
import captcha
import mailer
import models
import schemas
import totp
from database import engine, get_db
from repositories import HostRepository, MetricRepository, UserRepository
from strategies import MetricEvaluationStrategy, get_strategy

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)-5s %(name)s %(message)s",
)
log = logging.getLogger("app")

# Alembic owns the schema in production (see entrypoint.sh). This call is
# kept as a safety net for local scripts that import `main` directly
# without the Docker entrypoint (and for the test suite, which uses an
# in-memory SQLite engine and never hits Alembic).
models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="Custom DevOps Dashboard API")

# ─── CORS ──────────────────────────────────────────────────────────────
_cors_origins = [
    o.strip()
    for o in os.getenv("CORS_ALLOWED_ORIGINS", "http://localhost:5173").split(",")
    if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Policy constants (Task 4) ─────────────────────────────────────────
MAX_FAILED_ATTEMPTS = int(os.getenv("MAX_FAILED_ATTEMPTS", "5"))
LOCKOUT_MINUTES = int(os.getenv("LOCKOUT_MINUTES", "15"))
ACTIVATION_TOKEN_TTL_HOURS = int(os.getenv("ACTIVATION_TOKEN_TTL_HOURS", "24"))
PASSWORD_RESET_TTL_MINUTES = int(os.getenv("PASSWORD_RESET_TTL_MINUTES", "60"))
TWOFA_TICKET_TTL_MINUTES = 5

# A host is considered offline if its last heartbeat is older than 60 s.
HOST_OFFLINE_AFTER_SECONDS = 60


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ═══════════════════════════════════════════════════════════════════════
#  DEPENDENCY INJECTION — Repositories + Strategy (Lab #12)
# ═══════════════════════════════════════════════════════════════════════
# Routes receive repositories via FastAPI's `Depends`. This is the
# Repository pattern wired as a DI container entry: swap the repo (or
# its backing Session) in a test by overriding the dependency, no monkey
# patching required.
def get_user_repo(db: Session = Depends(get_db)) -> UserRepository:
    return UserRepository(db)


def get_host_repo(db: Session = Depends(get_db)) -> HostRepository:
    return HostRepository(db)


def get_metric_repo(db: Session = Depends(get_db)) -> MetricRepository:
    return MetricRepository(db)


def get_metric_strategy() -> MetricEvaluationStrategy:
    """Returns the active metric-evaluation strategy — picked by the
    ``METRIC_STRATEGY`` env var (``default`` | ``strict``)."""
    return get_strategy()


# ─── Health check ──────────────────────────────────────────────────────
@app.get("/health", tags=["infra"])
def health():
    return {"status": "ok"}


# ═══════════════════════════════════════════════════════════════════════
#  TELEMETRY (agent → backend)
# ═══════════════════════════════════════════════════════════════════════
def verify_agent_token(
    x_api_token: str = Header(..., alias="X-API-Token"),
    hosts: HostRepository = Depends(get_host_repo),
) -> models.Host:
    host = hosts.get_by_api_token(x_api_token)
    if not host:
        raise HTTPException(status_code=401, detail="Invalid API token")
    return host


@app.post("/api/telemetry", tags=["telemetry"])
def receive_telemetry(
    payload: schemas.HostMetricCreate,
    host: models.Host = Depends(verify_agent_token),
    hosts: HostRepository = Depends(get_host_repo),
    metrics: MetricRepository = Depends(get_metric_repo),
    strategy: MetricEvaluationStrategy = Depends(get_metric_strategy),
):
    # 1. Persist the metric snapshot + child container rows (repository
    #    encapsulates both INSERTs and the inner commit).
    db_metric = metrics.record_telemetry(host_id=host.id, payload=payload)

    # 2. Update heartbeat metadata on the host (is_online / last_seen_at
    #    / one-time OS fill).
    hosts.touch_heartbeat(
        host,
        os_info=payload.os_info,
        uptime_seconds=payload.uptime_seconds,
    )

    # 3. Evaluate with the active Strategy. A non-OK status is logged as
    #    a warning so operators can grep for host health regressions.
    evaluation = strategy.evaluate(
        cpu_percent=payload.cpu_percent,
        ram_percent=payload.ram_percent,
        disk_percent=payload.disk_percent,
    )
    if evaluation.status.value != "ok":
        log.warning(
            "[telemetry] host=%s strategy=%s status=%s reasons=%s",
            host.name,
            strategy.name,
            evaluation.status.value,
            "; ".join(evaluation.reasons),
        )

    return {
        "status": "success",
        "metric_id": db_metric.id,
        "evaluation": evaluation.as_dict(),
    }


# ═══════════════════════════════════════════════════════════════════════
#  DASHBOARD (JWT-protected) + RBAC
# ═══════════════════════════════════════════════════════════════════════
# ─── RBAC helpers (thin — delegate reads to HostRepository) ────────────
def _can_view_host(hosts: HostRepository, user: models.User, host: models.Host) -> bool:
    if user.is_admin:
        return True
    if host.owner_id == user.id:
        return True
    return hosts.has_access(host.id, user.id)


def _can_manage_host(user: models.User, host: models.Host) -> bool:
    """Who can share/revoke access and delete the host: owner or super-admin."""
    return bool(user.is_admin or host.owner_id == user.id)


def _require_host_view(
    host_id: int, hosts: HostRepository, user: models.User
) -> models.Host:
    host = hosts.get_by_id(host_id)
    if not host:
        raise HTTPException(status_code=404, detail="Хост не знайдено")
    if not _can_view_host(hosts, user, host):
        # Reveal nothing — same 404 the UI would see for a non-existent host.
        raise HTTPException(status_code=404, detail="Хост не знайдено")
    return host


def _require_host_manage(
    host_id: int, hosts: HostRepository, user: models.User
) -> models.Host:
    host = hosts.get_by_id(host_id)
    if not host:
        raise HTTPException(status_code=404, detail="Хост не знайдено")
    if not _can_manage_host(user, host):
        raise HTTPException(
            status_code=403,
            detail="Лише власник цього хоста або супер-адмін може керувати доступом",
        )
    return host


def _access_role_label(user: models.User, host: models.Host) -> str:
    if user.is_admin:
        return "admin"
    if host.owner_id == user.id:
        return "owner"
    return "shared"


# ─── Hosts list ─────────────────────────────────────────────────────────
@app.get("/api/hosts", response_model=list[schemas.HostDetail], tags=["dashboard"])
def get_hosts(
    user: models.User = Depends(auth.get_current_user),
    hosts: HostRepository = Depends(get_host_repo),
    metrics: MetricRepository = Depends(get_metric_repo),
    strategy: MetricEvaluationStrategy = Depends(get_metric_strategy),
):
    hosts.mark_stale_offline(offline_after_seconds=HOST_OFFLINE_AFTER_SECONDS)
    visible = hosts.visible_host_ids(user)
    if not visible:
        return []

    rows = hosts.list_by_ids(visible)
    out = []
    for h in rows:
        last = metrics.latest_for_host(h.id)
        owner_name = h.owner.username if h.owner else None
        # Evaluate current health against the active strategy so the UI
        # can colour-code tiles consistently with the server's own view.
        evaluation = strategy.evaluate(
            cpu_percent=last.cpu_percent if last else None,
            ram_percent=last.ram_percent if last else None,
            disk_percent=last.disk_percent if last else None,
        )
        out.append({
            "id": h.id,
            "name": h.name,
            "ip_address": h.ip_address,
            "port": h.port,
            "is_online": h.is_online,
            "os_info": h.os_info,
            "uptime_seconds": h.uptime_seconds,
            "last_seen_at": h.last_seen_at,
            "created_at": h.created_at,
            "cpu_percent": last.cpu_percent if last else None,
            "ram_percent": last.ram_percent if last else None,
            "disk_percent": last.disk_percent if last else None,
            "inode_percent": last.inode_percent if last else None,
            "owner_id": h.owner_id,
            "owner_username": owner_name,
            "my_access": _access_role_label(user, h),
            # Strategy-driven health status (non-breaking additive field;
            # HostDetail ignores unknown keys because Pydantic's default
            # is to drop them). Kept here so UIs that opt-in can read it.
            "health_status": evaluation.status.value,
        })
    return out


@app.get("/api/hosts/{host_id}/metrics", tags=["dashboard"])
def get_host_metrics(
    host_id: int,
    limit: int = 60,
    user: models.User = Depends(auth.get_current_user),
    hosts: HostRepository = Depends(get_host_repo),
    metrics: MetricRepository = Depends(get_metric_repo),
):
    _require_host_view(host_id, hosts, user)
    rows = metrics.latest_n_for_host(host_id, limit=limit)
    # Historically returned oldest-first for chart rendering.
    return list(reversed(rows))


@app.get("/api/hosts/{host_id}/containers", tags=["dashboard"])
def get_latest_containers(
    host_id: int,
    user: models.User = Depends(auth.get_current_user),
    hosts: HostRepository = Depends(get_host_repo),
    metrics: MetricRepository = Depends(get_metric_repo),
):
    _require_host_view(host_id, hosts, user)
    newest = metrics.latest_for_host(host_id)
    if not newest:
        return []
    rows = metrics.container_metrics_for(newest.id)
    return [
        {
            "container_id": r.container_id,
            "name": r.name,
            "state": r.state,
            "cpu_percent": r.cpu_percent,
            "ram_percent": r.ram_percent,
        }
        for r in rows
    ]


# ─── "Add System" — Beszel-style registration ──────────────────────────
def _generate_fake_ssh_key() -> str:
    blob = secrets.token_bytes(32)
    import base64 as _b64
    return "ssh-ed25519 " + _b64.b64encode(blob).decode("ascii")


def _render_compose(host: models.Host, hub_url: str) -> str:
    return (
        "services:\n"
        "  monitoring-agent:\n"
        "    image: your-registry/monitoring-agent:latest\n"
        f"    container_name: monitoring-agent-{host.name}\n"
        "    restart: unless-stopped\n"
        "    volumes:\n"
        "      - /var/run/docker.sock:/var/run/docker.sock:ro\n"
        "    environment:\n"
        f"      API_URL: {hub_url}/api/telemetry\n"
        f"      API_TOKEN: {host.api_token}\n"
        f"      LISTEN: {host.port or 45876}\n"
    )


@app.post(
    "/api/hosts",
    response_model=schemas.HostCreateResponse,
    tags=["dashboard"],
)
def register_host(
    body: schemas.HostCreateRequest,
    request: Request,
    user: models.User = Depends(auth.get_current_user),
    hosts: HostRepository = Depends(get_host_repo),
):
    # ANY logged-in user may create a host. The creator becomes its owner
    # ("admin of that server") — per the RBAC spec.
    if hosts.get_by_name(body.name):
        raise HTTPException(status_code=400, detail="Хост з такою назвою вже існує")

    token = secrets.token_urlsafe(32)
    pub_key = _generate_fake_ssh_key()
    host = models.Host(
        name=body.name,
        ip_address=body.ip_address,
        port=body.port or 45876,
        api_token=token,
        public_key=pub_key,
        is_online=False,
        owner_id=user.id,
    )
    hosts.add(host)

    hub_url = os.getenv("PUBLIC_HUB_URL") or str(request.base_url).rstrip("/")

    return schemas.HostCreateResponse(
        id=host.id,
        name=host.name,
        ip_address=host.ip_address,
        port=host.port or 45876,
        api_token=token,
        public_key=pub_key,
        hub_url=hub_url,
        docker_compose=_render_compose(host, hub_url),
    )


@app.delete("/api/hosts/{host_id}", tags=["dashboard"])
def delete_host(
    host_id: int,
    user: models.User = Depends(auth.get_current_user),
    hosts: HostRepository = Depends(get_host_repo),
):
    host = _require_host_manage(host_id, hosts, user)
    hosts.delete(host)
    return {"message": "deleted"}


# ─── Host access sharing (RBAC) ────────────────────────────────────────
@app.get(
    "/api/hosts/{host_id}/access",
    response_model=schemas.HostAccessBoard,
    tags=["dashboard"],
)
def host_access_board(
    host_id: int,
    user: models.User = Depends(auth.get_current_user),
    hosts: HostRepository = Depends(get_host_repo),
):
    """Who can see this host. Readable by anyone with view access;
    only owner / super-admin get `can_manage=True`."""
    host = _require_host_view(host_id, hosts, user)
    grants = hosts.list_access_grants(host_id)
    entries = []
    for g in grants:
        entries.append(schemas.HostAccessEntry(
            user_id=g.user.id,
            username=g.user.username,
            email=g.user.email,
            granted_by_id=g.granted_by_id,
            granted_by_username=g.granted_by.username if g.granted_by else None,
            granted_at=g.granted_at,
        ))
    return schemas.HostAccessBoard(
        host_id=host.id,
        owner_id=host.owner_id,
        owner_username=host.owner.username if host.owner else None,
        grants=entries,
        can_manage=_can_manage_host(user, host),
    )


@app.post(
    "/api/hosts/{host_id}/share",
    response_model=schemas.HostAccessEntry,
    tags=["dashboard"],
)
def share_host_access(
    host_id: int,
    body: schemas.ShareHostRequest,
    user: models.User = Depends(auth.get_current_user),
    hosts: HostRepository = Depends(get_host_repo),
    users: UserRepository = Depends(get_user_repo),
):
    host = _require_host_manage(host_id, hosts, user)
    target = users.find_by_email_or_username(body.identifier)
    if not target:
        # EXACT message the spec asks for: existing-user check.
        raise HTTPException(
            status_code=404,
            detail="Користувача з такою поштою або логіном не знайдено в системі",
        )
    if target.id == host.owner_id:
        raise HTTPException(
            status_code=400,
            detail="Власник уже має повний доступ до цього хоста",
        )
    if target.is_admin:
        raise HTTPException(
            status_code=400,
            detail="Супер-адмін уже має доступ до всіх хостів",
        )
    if hosts.get_access_grant(host.id, target.id):
        raise HTTPException(status_code=400, detail="Доступ уже надано")

    grant = hosts.add_access_grant(
        host_id=host.id, user_id=target.id, granted_by_id=user.id
    )

    return schemas.HostAccessEntry(
        user_id=target.id,
        username=target.username,
        email=target.email,
        granted_by_id=user.id,
        granted_by_username=user.username,
        granted_at=grant.granted_at,
    )


@app.delete(
    "/api/hosts/{host_id}/share/{user_id}",
    tags=["dashboard"],
)
def revoke_host_access(
    host_id: int,
    user_id: int,
    user: models.User = Depends(auth.get_current_user),
    hosts: HostRepository = Depends(get_host_repo),
):
    _require_host_manage(host_id, hosts, user)
    grant = hosts.get_access_grant(host_id, user_id)
    if not grant:
        raise HTTPException(status_code=404, detail="Запис доступу не знайдено")
    hosts.delete_access_grant(grant)
    return {"message": "revoked"}


# ─── Super-admin: access matrix across all users × all hosts ───────────
@app.get(
    "/api/admin/access-matrix",
    response_model=list[schemas.AdminUserAccessRow],
    tags=["admin"],
)
def admin_access_matrix(
    _admin: models.User = Depends(auth.get_current_admin),
    users: UserRepository = Depends(get_user_repo),
    hosts: HostRepository = Depends(get_host_repo),
):
    all_users = users.list_all()
    rows = []
    for u in all_users:
        rows.append(schemas.AdminUserAccessRow(
            user_id=u.id,
            username=u.username,
            email=u.email,
            is_admin=u.is_admin,
            owned_host_ids=hosts.owned_ids(u.id),
            shared_host_ids=hosts.shared_host_ids(u.id),
        ))
    return rows


@app.post(
    "/api/admin/users/{user_id}/grant/{host_id}",
    tags=["admin"],
)
def admin_grant_access(
    user_id: int,
    host_id: int,
    admin: models.User = Depends(auth.get_current_admin),
    users: UserRepository = Depends(get_user_repo),
    hosts: HostRepository = Depends(get_host_repo),
):
    target = users.get_by_id(user_id)
    host = hosts.get_by_id(host_id)
    if not target or not host:
        raise HTTPException(status_code=404, detail="User or host not found")
    if host.owner_id == user_id or target.is_admin:
        return {"message": "already-has-access"}
    if hosts.get_access_grant(host_id, user_id):
        return {"message": "already-granted"}
    hosts.add_access_grant(host_id=host_id, user_id=user_id, granted_by_id=admin.id)
    return {"message": "granted"}


@app.delete(
    "/api/admin/users/{user_id}/revoke/{host_id}",
    tags=["admin"],
)
def admin_revoke_access(
    user_id: int,
    host_id: int,
    _admin: models.User = Depends(auth.get_current_admin),
    hosts: HostRepository = Depends(get_host_repo),
):
    grant = hosts.get_access_grant(host_id, user_id)
    if not grant:
        raise HTTPException(status_code=404, detail="Grant not found")
    hosts.delete_access_grant(grant)
    return {"message": "revoked"}


# ═══════════════════════════════════════════════════════════════════════
#  AUDIT LOG HELPER (used by Tasks 1, 4, 5, 6)
# ═══════════════════════════════════════════════════════════════════════
def _log_login(
    db: Session,
    *,
    user_id: int | None,
    username_attempted: str | None,
    ip: str,
    status_: str,
    reason: str | None = None,
) -> None:
    db.add(
        models.LoginLog(
            user_id=user_id,
            username_attempted=username_attempted,
            ip_address=ip,
            status=status_,
            reason=reason,
        )
    )
    db.commit()


# ═══════════════════════════════════════════════════════════════════════
#  TASK 2 — CAPTCHA
# ═══════════════════════════════════════════════════════════════════════
@app.get("/api/captcha", response_model=schemas.CaptchaConfig, tags=["auth"])
def captcha_config():
    """Tell the frontend whether to render the reCAPTCHA widget."""
    return schemas.CaptchaConfig(
        enabled=captcha.is_enabled(),
        site_key=os.getenv("RECAPTCHA_SITE_KEY") or None,
    )


# ═══════════════════════════════════════════════════════════════════════
#  TASK 1 + TASK 2 + TASK 3 — REGISTRATION
# ═══════════════════════════════════════════════════════════════════════
def _issue_activation_token(db: Session, user: models.User) -> str:
    token = secrets.token_urlsafe(32)
    db.add(
        models.ActivationToken(
            user_id=user.id,
            token=token,
            expires_at=_now() + timedelta(hours=ACTIVATION_TOKEN_TTL_HOURS),
        )
    )
    db.commit()
    return token


@app.post("/api/register", tags=["auth"])
async def register_user(
    user: schemas.UserCreate,
    request: Request,
    db: Session = Depends(get_db),
    users: UserRepository = Depends(get_user_repo),
):
    ip = request.client.host if request.client else "unknown"

    # Task 2 — reCAPTCHA (bypassed when RECAPTCHA_SECRET_KEY not configured)
    if not await captcha.verify(user.captcha_token, remote_ip=ip):
        raise HTTPException(
            status_code=400, detail="CAPTCHA перевірка не пройдена"
        )

    if users.get_by_email(user.email):
        raise HTTPException(
            status_code=400, detail="Електронна пошта вже зареєстрована"
        )
    if users.get_by_username(user.username):
        raise HTTPException(
            status_code=400, detail="Ім'я користувача вже зайняте"
        )

    db_user = models.User(
        username=user.username,
        email=user.email,
        password_hash=auth.get_password_hash(user.password),
        # Task 3 — account starts INACTIVE; activation link flips the flag.
        is_active=False,
    )
    try:
        users.add(db_user)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Користувач вже існує")

    # Task 3 — issue + email activation token
    token = _issue_activation_token(db, db_user)
    mailer.send_activation_email(db_user.email, db_user.username, token)

    return {
        "message": (
            "Користувач успішно зареєстрований. "
            "Перевірте пошту і натисніть посилання для активації акаунта."
        )
    }


# ═══════════════════════════════════════════════════════════════════════
#  TASK 3 — ACCOUNT ACTIVATION
# ═══════════════════════════════════════════════════════════════════════
@app.get("/api/activate/{token}", tags=["auth"])
def activate_account(token: str, db: Session = Depends(get_db)):
    """Idempotent — a second click on the same link returns the same success
    message instead of an error. This covers:
      * users bouncing between tabs / hitting back,
      * React 18 StrictMode double-mounting the Activate page in dev,
      * email clients that pre-fetch links to scan for malware.
    Only truly invalid tokens (unknown, expired) are rejected."""
    row = (
        db.query(models.ActivationToken)
        .filter(models.ActivationToken.token == token)
        .first()
    )
    if not row:
        raise HTTPException(status_code=400, detail="Недійсне посилання активації")
    if row.expires_at < _now():
        raise HTTPException(status_code=400, detail="Термін дії посилання минув")

    user = db.query(models.User).filter(models.User.id == row.user_id).first()
    if not user:
        raise HTTPException(status_code=400, detail="Користувача не знайдено")

    # If the token was already consumed BUT the user is active, treat the
    # second request as a successful no-op. If the token was consumed and
    # the user is somehow NOT active (manual tampering), re-activate.
    if row.used_at is not None:
        if not user.is_active:
            user.is_active = True
            db.commit()
        return {"message": "Акаунт уже активовано. Тепер можна увійти."}

    user.is_active = True
    row.used_at = _now()
    db.commit()
    return {"message": "Акаунт успішно активовано. Тепер можна увійти."}


@app.post("/api/activation/resend", tags=["auth"])
def resend_activation(
    body: schemas.ResendActivationRequest,
    db: Session = Depends(get_db),
    users: UserRepository = Depends(get_user_repo),
):
    user = users.get_by_email(body.email)
    # Reply identically whether or not the email exists (anti-enumeration).
    if user and not user.is_active:
        token = _issue_activation_token(db, user)
        mailer.send_activation_email(user.email, user.username, token)
    return {"message": "Якщо акаунт існує, лист активації надіслано повторно."}


# ═══════════════════════════════════════════════════════════════════════
#  TASK 1 + TASK 4 + TASK 5 — LOGIN (with brute-force + optional 2FA)
# ═══════════════════════════════════════════════════════════════════════
# Short-lived "2FA ticket" JWT — issued only after password passes, carries
# the user id, and is the ONLY thing /api/2fa/verify-login will accept.
def _issue_twofa_ticket(user_id: int) -> str:
    return auth.create_access_token(
        data={"sub": f"2fa:{user_id}", "scope": "twofa"},
        expires_minutes=TWOFA_TICKET_TTL_MINUTES,
    )


def _consume_twofa_ticket(ticket: str) -> int:
    from jose import jwt, JWTError
    try:
        payload = jwt.decode(ticket, auth.SECRET_KEY, algorithms=[auth.ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=400, detail="Недійсний 2FA ticket")
    if payload.get("scope") != "twofa":
        raise HTTPException(status_code=400, detail="Недійсний 2FA ticket")
    sub = payload.get("sub", "")
    if not sub.startswith("2fa:"):
        raise HTTPException(status_code=400, detail="Недійсний 2FA ticket")
    try:
        return int(sub.removeprefix("2fa:"))
    except ValueError:
        raise HTTPException(status_code=400, detail="Недійсний 2FA ticket")


def _is_temporarily_locked(user: models.User) -> bool:
    return bool(user.locked_until and user.locked_until > _now())


@app.post("/api/login", response_model=schemas.LoginResponse, tags=["auth"])
def login_for_access_token(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
    users: UserRepository = Depends(get_user_repo),
):
    ip = request.client.host if request.client else "unknown"
    user = users.get_by_username(form_data.username)

    # 1. Hard lock (admin-set) — check BEFORE touching the password. We also
    #    don't want "wrong password" responses to leak that the account exists
    #    while locked. Rely on identical "bad_credentials" message instead.
    if user and user.is_locked:
        _log_login(
            db,
            user_id=user.id,
            username_attempted=form_data.username,
            ip=ip,
            status_="locked",
            reason="admin_lock",
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Акаунт заблоковано адміністратором",
        )

    # 2. Soft lock (brute-force protector) — also BEFORE the password check,
    #    otherwise further bad guesses just reset the clock on every attempt.
    if user and _is_temporarily_locked(user):
        _log_login(
            db,
            user_id=user.id,
            username_attempted=form_data.username,
            ip=ip,
            status_="locked",
            reason="brute_force_lock",
        )
        mins = int((user.locked_until - _now()).total_seconds() // 60) + 1
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail=(
                f"Акаунт тимчасово заблоковано через значну кількість "
                f"невдалих спроб. Спробуйте через {mins} хв."
            ),
        )

    # 3. Unknown user OR wrong password → identical error (no enumeration).
    #    If a user existed, bump its failed-attempt counter.
    if not user or not auth.verify_password(form_data.password, user.password_hash):
        if user:
            users.bump_failed_attempt(
                user, max_attempts=MAX_FAILED_ATTEMPTS, lock_minutes=LOCKOUT_MINUTES
            )
            if user.failed_login_attempts >= MAX_FAILED_ATTEMPTS:
                log.warning(
                    "Account %s temporarily locked after %s failed attempts",
                    user.username, user.failed_login_attempts,
                )
        _log_login(
            db,
            user_id=user.id if user else None,
            username_attempted=form_data.username,
            ip=ip,
            status_="failed",
            reason="bad_credentials",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неправильний логін або пароль",
        )

    # 4. Not activated (Task 3)
    if not user.is_active:
        _log_login(
            db,
            user_id=user.id,
            username_attempted=form_data.username,
            ip=ip,
            status_="failed",
            reason="inactive",
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Акаунт не активовано. Перевірте пошту для активації.",
        )

    # 5. Credentials OK — reset the counter.
    users.reset_failed_attempts(user)

    # 6. If 2FA is enabled, DON'T issue the JWT yet. Return a short-lived
    #    ticket and require POST /api/2fa/verify-login.
    if user.is_2fa_enabled and user.totp_secret:
        _log_login(
            db,
            user_id=user.id,
            username_attempted=form_data.username,
            ip=ip,
            status_="pending",
            reason="2fa_required",
        )
        return schemas.LoginResponse(
            twofa_required=True,
            twofa_ticket=_issue_twofa_ticket(user.id),
        )

    # 7. Full success.
    access_token = auth.create_access_token(
        data={"sub": user.username, "role": user.role.value}
    )
    _log_login(
        db,
        user_id=user.id,
        username_attempted=form_data.username,
        ip=ip,
        status_="success",
    )
    return schemas.LoginResponse(access_token=access_token, token_type="bearer")


@app.post("/api/2fa/verify-login", response_model=schemas.Token, tags=["auth"])
def verify_login_2fa(
    body: schemas.TwoFALoginVerify,
    request: Request,
    db: Session = Depends(get_db),
    users: UserRepository = Depends(get_user_repo),
):
    user_id = _consume_twofa_ticket(body.ticket)
    user = users.get_by_id(user_id)
    ip = request.client.host if request.client else "unknown"
    if not user or not user.is_2fa_enabled or not user.totp_secret:
        raise HTTPException(status_code=400, detail="2FA не ввімкнено для цього акаунта")
    if not totp.verify(user.totp_secret, body.code):
        users.bump_failed_attempt(
            user, max_attempts=MAX_FAILED_ATTEMPTS, lock_minutes=LOCKOUT_MINUTES
        )
        _log_login(
            db,
            user_id=user.id,
            username_attempted=user.username,
            ip=ip,
            status_="failed",
            reason="bad_2fa",
        )
        raise HTTPException(status_code=401, detail="Невірний код 2FA")

    users.reset_failed_attempts(user)
    access_token = auth.create_access_token(
        data={"sub": user.username, "role": user.role.value}
    )
    _log_login(
        db,
        user_id=user.id,
        username_attempted=user.username,
        ip=ip,
        status_="success",
        reason="2fa_ok",
    )
    return {"access_token": access_token, "token_type": "bearer"}


# ═══════════════════════════════════════════════════════════════════════
#  TASK 1 — PROFILE + LOGOUT
# ═══════════════════════════════════════════════════════════════════════
@app.get("/api/me", response_model=schemas.UserProfile, tags=["auth"])
def read_me(user: models.User = Depends(auth.get_current_user)):
    return user


@app.post("/api/logout", tags=["auth"])
def logout(
    request: Request,
    user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(get_db),
):
    ip = request.client.host if request.client else "unknown"
    _log_login(
        db,
        user_id=user.id,
        username_attempted=user.username,
        ip=ip,
        status_="success",
        reason="logout",
    )
    return {"message": "logged out"}


# ═══════════════════════════════════════════════════════════════════════
#  TASK 5 — 2FA ENROLL / ENABLE / DISABLE (self-service)
# ═══════════════════════════════════════════════════════════════════════
@app.post("/api/2fa/setup", response_model=schemas.TwoFAEnrollResponse, tags=["auth"])
def twofa_setup(
    user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(get_db),
):
    """Generate (or regenerate) a TOTP secret for the user.

    The secret is persisted but `is_2fa_enabled` stays False until the user
    proves possession via /api/2fa/enable with a valid 6-digit code.
    """
    secret = totp.new_secret()
    user.totp_secret = secret
    user.is_2fa_enabled = False  # must re-prove ownership
    db.commit()
    uri = totp.provisioning_uri(secret, account_name=user.email)
    return schemas.TwoFAEnrollResponse(
        secret=secret,
        otpauth_url=uri,
        qr_png_data_url=totp.qr_png_data_url(uri),
    )


@app.post("/api/2fa/enable", tags=["auth"])
def twofa_enable(
    body: schemas.TwoFAVerifyRequest,
    user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(get_db),
):
    if not user.totp_secret:
        raise HTTPException(status_code=400, detail="Спочатку виконайте /api/2fa/setup")
    if not totp.verify(user.totp_secret, body.code):
        raise HTTPException(status_code=400, detail="Невірний код")
    user.is_2fa_enabled = True
    db.commit()
    return {"message": "2FA увімкнено"}


@app.post("/api/2fa/disable", tags=["auth"])
def twofa_disable(
    body: schemas.TwoFADisableRequest,
    user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(get_db),
):
    # Confirm identity with the password (so a stolen session can't flip it off).
    if not auth.verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Невірний пароль")
    user.is_2fa_enabled = False
    user.totp_secret = None
    db.commit()
    return {"message": "2FA вимкнено"}


# ═══════════════════════════════════════════════════════════════════════
#  TASK 7 — PASSWORD RECOVERY
# ═══════════════════════════════════════════════════════════════════════
@app.post("/api/password/forgot", tags=["auth"])
def password_forgot(
    body: schemas.PasswordForgotRequest,
    db: Session = Depends(get_db),
    users: UserRepository = Depends(get_user_repo),
):
    user = users.get_by_email(body.email)
    # Always answer identically — anti-enumeration.
    if user:
        token = secrets.token_urlsafe(32)
        db.add(
            models.PasswordResetToken(
                user_id=user.id,
                token=token,
                expires_at=_now() + timedelta(minutes=PASSWORD_RESET_TTL_MINUTES),
            )
        )
        db.commit()
        mailer.send_password_reset_email(user.email, user.username, token)
    return {"message": "Якщо акаунт існує, лист зі скиданням пароля надіслано."}


@app.post("/api/password/reset", tags=["auth"])
def password_reset(
    body: schemas.PasswordResetRequest, db: Session = Depends(get_db)
):
    row = (
        db.query(models.PasswordResetToken)
        .filter(models.PasswordResetToken.token == body.token)
        .first()
    )
    if not row:
        raise HTTPException(status_code=400, detail="Недійсне посилання")
    if row.used_at is not None:
        raise HTTPException(status_code=400, detail="Посилання вже використане")
    if row.expires_at < _now():
        raise HTTPException(status_code=400, detail="Термін дії посилання минув")

    user = db.query(models.User).filter(models.User.id == row.user_id).first()
    if not user:
        raise HTTPException(status_code=400, detail="Користувача не знайдено")

    user.password_hash = auth.get_password_hash(body.new_password)
    user.failed_login_attempts = 0
    user.locked_until = None
    row.used_at = _now()
    db.commit()
    return {"message": "Пароль успішно оновлено. Тепер можна увійти."}


# ═══════════════════════════════════════════════════════════════════════
#  TASK 4 — ADMIN AUDIT PANEL
# ═══════════════════════════════════════════════════════════════════════
@app.get(
    "/api/admin/login-logs",
    response_model=list[schemas.LoginLogOut],
    tags=["admin"],
)
def admin_login_logs(
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
    _admin: models.User = Depends(auth.get_current_admin),
):
    return (
        db.query(models.LoginLog)
        .order_by(models.LoginLog.id.desc())
        .offset(offset)
        .limit(min(limit, 500))
        .all()
    )


@app.get(
    "/api/admin/users",
    response_model=list[schemas.AdminUserOut],
    tags=["admin"],
)
def admin_users(
    _admin: models.User = Depends(auth.get_current_admin),
    users: UserRepository = Depends(get_user_repo),
):
    return users.list_all()


@app.post("/api/admin/users/{user_id}/lock", tags=["admin"])
def admin_lock_user(
    user_id: int,
    admin: models.User = Depends(auth.get_current_admin),
    users: UserRepository = Depends(get_user_repo),
):
    user = users.get_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Користувача не знайдено")
    if user.id == admin.id:
        raise HTTPException(status_code=400, detail="Не можна заблокувати власний акаунт")
    user.is_locked = True
    users.save()
    return {"message": f"Користувача {user.username} заблоковано"}


@app.post("/api/admin/users/{user_id}/unlock", tags=["admin"])
def admin_unlock_user(
    user_id: int,
    _admin: models.User = Depends(auth.get_current_admin),
    users: UserRepository = Depends(get_user_repo),
):
    user = users.get_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Користувача не знайдено")
    user.is_locked = False
    user.failed_login_attempts = 0
    user.locked_until = None
    users.save()
    return {"message": f"Користувача {user.username} розблоковано"}


# ═══════════════════════════════════════════════════════════════════════
#  TASK 6 — GOOGLE OPENID CONNECT
# ═══════════════════════════════════════════════════════════════════════
class GoogleAuthRequest(BaseModel):
    token: str


@app.post("/api/auth/google", tags=["auth"])
async def google_auth(
    body: GoogleAuthRequest,
    request: Request,
    db: Session = Depends(get_db),
    users: UserRepository = Depends(get_user_repo),
):
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.get(
            "https://oauth2.googleapis.com/tokeninfo",
            params={"id_token": body.token},
        )
    if response.status_code != 200:
        raise HTTPException(status_code=400, detail="Недійсний Google токен")

    info = response.json()
    email = info.get("email")
    if not email:
        raise HTTPException(
            status_code=400, detail="Електронна пошта не знайдена у профілі"
        )

    expected_aud = os.getenv("GOOGLE_CLIENT_ID")
    if expected_aud and info.get("aud") != expected_aud:
        raise HTTPException(status_code=400, detail="Невідповідність Google Client ID")

    user = users.get_by_email(email)
    if not user:
        random_password = str(uuid.uuid4()) + "A1!"
        user = models.User(
            username=info.get("name") or email.split("@")[0],
            email=email,
            password_hash=auth.get_password_hash(random_password),
            is_active=True,  # Google already verified the email
        )
        try:
            users.add(user)
        except IntegrityError:
            db.rollback()
            user = models.User(
                username=f"{email.split('@')[0]}-{secrets.token_hex(3)}",
                email=email,
                password_hash=auth.get_password_hash(random_password),
                is_active=True,
            )
            users.add(user)

    if user.is_locked:
        raise HTTPException(status_code=403, detail="Акаунт заблоковано адміністратором")

    access_token = auth.create_access_token(
        data={"sub": user.username, "role": user.role.value}
    )
    ip = request.client.host if request.client else "unknown"
    _log_login(
        db,
        user_id=user.id,
        username_attempted=user.username,
        ip=ip,
        status_="success",
        reason="google_oauth",
    )
    return {"access_token": access_token, "token_type": "bearer"}
