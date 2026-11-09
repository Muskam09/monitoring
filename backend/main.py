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

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)-5s %(name)s %(message)s",
)
log = logging.getLogger("app")

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


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ─── Health check ──────────────────────────────────────────────────────
@app.get("/health", tags=["infra"])
def health():
    return {"status": "ok"}


# ═══════════════════════════════════════════════════════════════════════
#  TELEMETRY (agent → backend)
# ═══════════════════════════════════════════════════════════════════════
def verify_agent_token(
    x_api_token: str = Header(..., alias="X-API-Token"),
    db: Session = Depends(get_db),
) -> models.Host:
    host = (
        db.query(models.Host)
        .filter(models.Host.api_token == x_api_token)
        .first()
    )
    if not host:
        raise HTTPException(status_code=401, detail="Invalid API token")
    return host


@app.post("/api/telemetry", tags=["telemetry"])
def receive_telemetry(
    payload: schemas.HostMetricCreate,
    host: models.Host = Depends(verify_agent_token),
    db: Session = Depends(get_db),
):
    # New metric row with the FULL set of host-level stats the agent now sends.
    db_metric = models.HostMetric(
        host_id=host.id,
        cpu_percent=payload.cpu_percent,
        ram_percent=payload.ram_percent,
        disk_percent=payload.disk_percent,
        inode_percent=payload.inode_percent,
        disk_read_bytes_per_sec=payload.disk_read_bytes_per_sec,
        disk_write_bytes_per_sec=payload.disk_write_bytes_per_sec,
        net_external_rx_bps=payload.net_external_rx_bps,
        net_external_tx_bps=payload.net_external_tx_bps,
        net_internal_rx_bps=payload.net_internal_rx_bps,
        net_internal_tx_bps=payload.net_internal_tx_bps,
    )
    db.add(db_metric)
    db.commit()
    db.refresh(db_metric)

    for container in payload.containers:
        db.add(
            models.ContainerMetric(
                host_metric_id=db_metric.id,
                container_id=container.container_id,
                name=container.name,
                state=container.state,
                cpu_percent=container.cpu_percent,
                ram_percent=container.ram_percent,
            )
        )

    host.is_online = True  # type: ignore[assignment]
    host.last_seen_at = _now()
    # One-time: fill OS / uptime on first heartbeat if not already set.
    if payload.os_info and not host.os_info:
        host.os_info = payload.os_info
    if payload.uptime_seconds is not None:
        host.uptime_seconds = payload.uptime_seconds
    db.commit()
    return {"status": "success", "metric_id": db_metric.id}


# ═══════════════════════════════════════════════════════════════════════
#  DASHBOARD (JWT-protected) + RBAC
# ═══════════════════════════════════════════════════════════════════════
# A host is considered offline if its last heartbeat is older than 60 s.
HOST_OFFLINE_AFTER_SECONDS = 60


def _mark_stale_offline(db: Session) -> None:
    cutoff = _now() - timedelta(seconds=HOST_OFFLINE_AFTER_SECONDS)
    (
        db.query(models.Host)
        .filter(models.Host.last_seen_at != None)  # noqa: E711
        .filter(models.Host.last_seen_at < cutoff)
        .filter(models.Host.is_online.is_(True))
        .update({models.Host.is_online: False}, synchronize_session=False)
    )
    db.commit()


# ─── RBAC helpers ──────────────────────────────────────────────────────
def _visible_host_ids(db: Session, user: models.User) -> set[int]:
    """Return the set of host IDs the user is allowed to see.

    Rules:
      - Super-admin (User.is_admin=True) sees EVERYTHING.
      - A regular user sees (hosts they own) ∪ (hosts granted via HostAccess).
    """
    if user.is_admin:
        return {h[0] for h in db.query(models.Host.id).all()}
    owned = {h[0] for h in db.query(models.Host.id).filter(models.Host.owner_id == user.id).all()}
    shared = {
        h[0] for h in db.query(models.HostAccess.host_id)
        .filter(models.HostAccess.user_id == user.id).all()
    }
    return owned | shared


def _can_view_host(db: Session, user: models.User, host: models.Host) -> bool:
    if user.is_admin:
        return True
    if host.owner_id == user.id:
        return True
    return (
        db.query(models.HostAccess)
        .filter(models.HostAccess.host_id == host.id)
        .filter(models.HostAccess.user_id == user.id)
        .first()
        is not None
    )


def _can_manage_host(user: models.User, host: models.Host) -> bool:
    """Who can share/revoke access and delete the host: owner or super-admin."""
    return user.is_admin or host.owner_id == user.id


def _require_host_view(
    host_id: int, db: Session, user: models.User
) -> models.Host:
    host = db.query(models.Host).filter(models.Host.id == host_id).first()
    if not host:
        raise HTTPException(status_code=404, detail="Хост не знайдено")
    if not _can_view_host(db, user, host):
        # Reveal nothing — same 404 the UI would see for a non-existent host.
        raise HTTPException(status_code=404, detail="Хост не знайдено")
    return host


def _require_host_manage(
    host_id: int, db: Session, user: models.User
) -> models.Host:
    host = db.query(models.Host).filter(models.Host.id == host_id).first()
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
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.get_current_user),
):
    _mark_stale_offline(db)
    visible = _visible_host_ids(db, user)
    if not visible:
        return []
    hosts = (
        db.query(models.Host)
        .filter(models.Host.id.in_(visible))
        .order_by(models.Host.id.asc())
        .all()
    )
    out = []
    for h in hosts:
        last = (
            db.query(models.HostMetric)
            .filter(models.HostMetric.host_id == h.id)
            .order_by(models.HostMetric.timestamp.desc())
            .first()
        )
        owner_name = h.owner.username if h.owner else None
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
        })
    return out


@app.get("/api/hosts/{host_id}/metrics", tags=["dashboard"])
def get_host_metrics(
    host_id: int,
    limit: int = 60,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.get_current_user),
):
    _require_host_view(host_id, db, user)
    rows = (
        db.query(models.HostMetric)
        .filter(models.HostMetric.host_id == host_id)
        .order_by(models.HostMetric.timestamp.desc())
        .limit(min(limit, 240))
        .all()
    )
    return list(reversed(rows))


@app.get("/api/hosts/{host_id}/containers", tags=["dashboard"])
def get_latest_containers(
    host_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.get_current_user),
):
    _require_host_view(host_id, db, user)
    newest = (
        db.query(models.HostMetric)
        .filter(models.HostMetric.host_id == host_id)
        .order_by(models.HostMetric.timestamp.desc())
        .first()
    )
    if not newest:
        return []
    rows = (
        db.query(models.ContainerMetric)
        .filter(models.ContainerMetric.host_metric_id == newest.id)
        .order_by(models.ContainerMetric.name.asc())
        .all()
    )
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
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.get_current_user),
):
    # ANY logged-in user may create a host. The creator becomes its owner
    # ("admin of that server") — per the new RBAC spec.
    if db.query(models.Host).filter(models.Host.name == body.name).first():
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
    db.add(host)
    db.commit()
    db.refresh(host)

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
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.get_current_user),
):
    host = _require_host_manage(host_id, db, user)
    db.delete(host)
    db.commit()
    return {"message": "deleted"}


# ─── Host access sharing (RBAC) ────────────────────────────────────────
def _resolve_user_by_identifier(db: Session, identifier: str) -> models.User | None:
    """Accept either email or username. Case-insensitive on email."""
    ident = identifier.strip()
    if not ident:
        return None
    # Try username first (usernames are case-sensitive per our model)
    u = db.query(models.User).filter(models.User.username == ident).first()
    if u:
        return u
    # Then try email (lowercased)
    return (
        db.query(models.User)
        .filter(models.User.email.ilike(ident))
        .first()
    )


@app.get(
    "/api/hosts/{host_id}/access",
    response_model=schemas.HostAccessBoard,
    tags=["dashboard"],
)
def host_access_board(
    host_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.get_current_user),
):
    """Who can see this host. Readable by anyone with view access;
    only owner / super-admin get `can_manage=True`."""
    host = _require_host_view(host_id, db, user)
    grants = (
        db.query(models.HostAccess)
        .filter(models.HostAccess.host_id == host_id)
        .all()
    )
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
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.get_current_user),
):
    host = _require_host_manage(host_id, db, user)
    target = _resolve_user_by_identifier(db, body.identifier)
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

    existing = (
        db.query(models.HostAccess)
        .filter(models.HostAccess.host_id == host.id)
        .filter(models.HostAccess.user_id == target.id)
        .first()
    )
    if existing:
        raise HTTPException(status_code=400, detail="Доступ уже надано")

    grant = models.HostAccess(
        host_id=host.id,
        user_id=target.id,
        granted_by_id=user.id,
    )
    db.add(grant)
    db.commit()
    db.refresh(grant)

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
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.get_current_user),
):
    _require_host_manage(host_id, db, user)
    grant = (
        db.query(models.HostAccess)
        .filter(models.HostAccess.host_id == host_id)
        .filter(models.HostAccess.user_id == user_id)
        .first()
    )
    if not grant:
        raise HTTPException(status_code=404, detail="Запис доступу не знайдено")
    db.delete(grant)
    db.commit()
    return {"message": "revoked"}


# ─── Super-admin: access matrix across all users × all hosts ───────────
@app.get(
    "/api/admin/access-matrix",
    response_model=list[schemas.AdminUserAccessRow],
    tags=["admin"],
)
def admin_access_matrix(
    db: Session = Depends(get_db),
    _admin: models.User = Depends(auth.get_current_admin),
):
    users = db.query(models.User).order_by(models.User.id.asc()).all()
    rows = []
    for u in users:
        owned = [
            h[0] for h in db.query(models.Host.id)
            .filter(models.Host.owner_id == u.id).all()
        ]
        shared = [
            h[0] for h in db.query(models.HostAccess.host_id)
            .filter(models.HostAccess.user_id == u.id).all()
        ]
        rows.append(schemas.AdminUserAccessRow(
            user_id=u.id,
            username=u.username,
            email=u.email,
            is_admin=u.is_admin,
            owned_host_ids=owned,
            shared_host_ids=shared,
        ))
    return rows


@app.post(
    "/api/admin/users/{user_id}/grant/{host_id}",
    tags=["admin"],
)
def admin_grant_access(
    user_id: int,
    host_id: int,
    db: Session = Depends(get_db),
    admin: models.User = Depends(auth.get_current_admin),
):
    target = db.query(models.User).filter(models.User.id == user_id).first()
    host = db.query(models.Host).filter(models.Host.id == host_id).first()
    if not target or not host:
        raise HTTPException(status_code=404, detail="User or host not found")
    if host.owner_id == user_id or target.is_admin:
        return {"message": "already-has-access"}
    exists = (
        db.query(models.HostAccess)
        .filter(models.HostAccess.host_id == host_id)
        .filter(models.HostAccess.user_id == user_id)
        .first()
    )
    if exists:
        return {"message": "already-granted"}
    db.add(models.HostAccess(host_id=host_id, user_id=user_id, granted_by_id=admin.id))
    db.commit()
    return {"message": "granted"}


@app.delete(
    "/api/admin/users/{user_id}/revoke/{host_id}",
    tags=["admin"],
)
def admin_revoke_access(
    user_id: int,
    host_id: int,
    db: Session = Depends(get_db),
    _admin: models.User = Depends(auth.get_current_admin),
):
    grant = (
        db.query(models.HostAccess)
        .filter(models.HostAccess.host_id == host_id)
        .filter(models.HostAccess.user_id == user_id)
        .first()
    )
    if not grant:
        raise HTTPException(status_code=404, detail="Grant not found")
    db.delete(grant)
    db.commit()
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
):
    ip = request.client.host if request.client else "unknown"

    # Task 2 — reCAPTCHA (bypassed when RECAPTCHA_SECRET_KEY not configured)
    if not await captcha.verify(user.captcha_token, remote_ip=ip):
        raise HTTPException(
            status_code=400, detail="CAPTCHA перевірка не пройдена"
        )

    if db.query(models.User).filter(models.User.email == user.email).first():
        raise HTTPException(
            status_code=400, detail="Електронна пошта вже зареєстрована"
        )
    if db.query(models.User).filter(models.User.username == user.username).first():
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
    db.add(db_user)
    try:
        db.commit()
        db.refresh(db_user)
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
    body: schemas.ResendActivationRequest, db: Session = Depends(get_db)
):
    user = db.query(models.User).filter(models.User.email == body.email).first()
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


def _bump_failed_attempt(db: Session, user: models.User) -> None:
    user.failed_login_attempts = (user.failed_login_attempts or 0) + 1
    if user.failed_login_attempts >= MAX_FAILED_ATTEMPTS:
        user.locked_until = _now() + timedelta(minutes=LOCKOUT_MINUTES)
        log.warning(
            "Account %s temporarily locked after %s failed attempts",
            user.username, user.failed_login_attempts,
        )
    db.commit()


def _reset_failed_attempts(db: Session, user: models.User) -> None:
    user.failed_login_attempts = 0
    user.locked_until = None
    db.commit()


@app.post("/api/login", response_model=schemas.LoginResponse, tags=["auth"])
def login_for_access_token(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    ip = request.client.host if request.client else "unknown"
    user = (
        db.query(models.User)
        .filter(models.User.username == form_data.username)
        .first()
    )

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
            _bump_failed_attempt(db, user)
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
    _reset_failed_attempts(db, user)

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
):
    user_id = _consume_twofa_ticket(body.ticket)
    user = db.query(models.User).filter(models.User.id == user_id).first()
    ip = request.client.host if request.client else "unknown"
    if not user or not user.is_2fa_enabled or not user.totp_secret:
        raise HTTPException(status_code=400, detail="2FA не ввімкнено для цього акаунта")
    if not totp.verify(user.totp_secret, body.code):
        _bump_failed_attempt(db, user)
        _log_login(
            db,
            user_id=user.id,
            username_attempted=user.username,
            ip=ip,
            status_="failed",
            reason="bad_2fa",
        )
        raise HTTPException(status_code=401, detail="Невірний код 2FA")

    _reset_failed_attempts(db, user)
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
    body: schemas.PasswordForgotRequest, db: Session = Depends(get_db)
):
    user = db.query(models.User).filter(models.User.email == body.email).first()
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
    db: Session = Depends(get_db),
    _admin: models.User = Depends(auth.get_current_admin),
):
    return db.query(models.User).order_by(models.User.id.asc()).all()


@app.post("/api/admin/users/{user_id}/lock", tags=["admin"])
def admin_lock_user(
    user_id: int,
    db: Session = Depends(get_db),
    admin: models.User = Depends(auth.get_current_admin),
):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Користувача не знайдено")
    if user.id == admin.id:
        raise HTTPException(status_code=400, detail="Не можна заблокувати власний акаунт")
    user.is_locked = True
    db.commit()
    return {"message": f"Користувача {user.username} заблоковано"}


@app.post("/api/admin/users/{user_id}/unlock", tags=["admin"])
def admin_unlock_user(
    user_id: int,
    db: Session = Depends(get_db),
    _admin: models.User = Depends(auth.get_current_admin),
):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Користувача не знайдено")
    user.is_locked = False
    user.failed_login_attempts = 0
    user.locked_until = None
    db.commit()
    return {"message": f"Користувача {user.username} розблоковано"}


# ═══════════════════════════════════════════════════════════════════════
#  TASK 6 — GOOGLE OPENID CONNECT
# ═══════════════════════════════════════════════════════════════════════
class GoogleAuthRequest(BaseModel):
    token: str


@app.post("/api/auth/google", tags=["auth"])
async def google_auth(
    body: GoogleAuthRequest, request: Request, db: Session = Depends(get_db)
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

    user = db.query(models.User).filter(models.User.email == email).first()
    if not user:
        random_password = str(uuid.uuid4()) + "A1!"
        user = models.User(
            username=info.get("name") or email.split("@")[0],
            email=email,
            password_hash=auth.get_password_hash(random_password),
            is_active=True,  # Google already verified the email
        )
        db.add(user)
        try:
            db.commit()
            db.refresh(user)
        except IntegrityError:
            db.rollback()
            user = models.User(
                username=f"{email.split('@')[0]}-{secrets.token_hex(3)}",
                email=email,
                password_hash=auth.get_password_hash(random_password),
                is_active=True,
            )
            db.add(user)
            db.commit()
            db.refresh(user)

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
