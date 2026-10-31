"""SQLAlchemy ORM models for the monitoring dashboard."""
import enum
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
)
from sqlalchemy.orm import relationship

from database import Base


def _utcnow() -> datetime:
    """Timezone-aware UTC "now" — replaces deprecated datetime.utcnow()."""
    return datetime.now(timezone.utc)


class RoleEnum(str, enum.Enum):
    editor = "editor"
    viewer = "viewer"


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    role = Column(Enum(RoleEnum), default=RoleEnum.viewer, nullable=False)

    # Task 3 — email activation
    is_active = Column(Boolean, default=False, nullable=False)

    # Task 4 — brute-force protection
    # `failed_login_attempts` resets on every success. `locked_until` is a
    # soft, temporary lock set by the brute-force protector. `is_locked`
    # is a hard, admin-set lock (manual block/unblock).
    failed_login_attempts = Column(Integer, default=0, nullable=False)
    locked_until = Column(DateTime(timezone=True), nullable=True)
    is_locked = Column(Boolean, default=False, nullable=False)

    # Task 5 — 2FA (TOTP)
    totp_secret = Column(String, nullable=True)
    is_2fa_enabled = Column(Boolean, default=False, nullable=False)

    # Admin flag (for Task 4 audit panel & general permission checks)
    is_admin = Column(Boolean, default=False, nullable=False)

    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

    # Reverse relationships (cascade-delete tokens if user is removed)
    activation_tokens = relationship(
        "ActivationToken", back_populates="user", cascade="all, delete-orphan"
    )
    password_reset_tokens = relationship(
        "PasswordResetToken", back_populates="user", cascade="all, delete-orphan"
    )


class ActivationToken(Base):
    """Task 3 — one-time email-activation token."""

    __tablename__ = "activation_tokens"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    # token is stored verbatim because it is single-use and has a short TTL;
    # URL-safe random 32-byte secret has 256 bits of entropy.
    token = Column(String, unique=True, index=True, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

    user = relationship("User", back_populates="activation_tokens")


class PasswordResetToken(Base):
    """Task 7 — one-time password-reset token."""

    __tablename__ = "password_reset_tokens"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    token = Column(String, unique=True, index=True, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

    user = relationship("User", back_populates="password_reset_tokens")


class Host(Base):
    __tablename__ = "hosts"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True, nullable=False)
    ip_address = Column(String, nullable=True)
    api_token = Column(String, unique=True, index=True, nullable=False)
    is_online = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

    metrics = relationship(
        "HostMetric", back_populates="host", cascade="all, delete-orphan"
    )


class HostMetric(Base):
    __tablename__ = "host_metrics"
    id = Column(Integer, primary_key=True, index=True)
    host_id = Column(Integer, ForeignKey("hosts.id"))
    cpu_percent = Column(Float, nullable=False)
    ram_percent = Column(Float, nullable=False)
    disk_percent = Column(Float, nullable=False)
    timestamp = Column(DateTime(timezone=True), default=_utcnow, index=True)

    host = relationship("Host", back_populates="metrics")
    container_metrics = relationship(
        "ContainerMetric",
        back_populates="parent_metric",
        cascade="all, delete-orphan",
    )


class ContainerMetric(Base):
    __tablename__ = "container_metrics"
    id = Column(Integer, primary_key=True, index=True)
    host_metric_id = Column(Integer, ForeignKey("host_metrics.id"))
    container_id = Column(String, nullable=False)
    name = Column(String, nullable=False)
    state = Column(String, nullable=False)  # running, exited, etc.
    cpu_percent = Column(Float, nullable=False)
    ram_percent = Column(Float, nullable=False)

    parent_metric = relationship("HostMetric", back_populates="container_metrics")


class LoginLog(Base):
    """Audit log of authentication attempts (fed by /api/login & /api/auth/google)."""

    __tablename__ = "login_logs"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    username_attempted = Column(String, nullable=True)
    ip_address = Column(String, nullable=False)
    status = Column(String, nullable=False)  # "success" | "failed" | "locked"
    reason = Column(String, nullable=True)
    timestamp = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
