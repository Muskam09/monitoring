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
    UniqueConstraint,
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

    is_active = Column(Boolean, default=False, nullable=False)

    failed_login_attempts = Column(Integer, default=0, nullable=False)
    locked_until = Column(DateTime(timezone=True), nullable=True)
    is_locked = Column(Boolean, default=False, nullable=False)

    totp_secret = Column(String, nullable=True)
    is_2fa_enabled = Column(Boolean, default=False, nullable=False)

    is_admin = Column(Boolean, default=False, nullable=False)

    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

    activation_tokens = relationship(
        "ActivationToken", back_populates="user", cascade="all, delete-orphan"
    )
    password_reset_tokens = relationship(
        "PasswordResetToken", back_populates="user", cascade="all, delete-orphan"
    )


class ActivationToken(Base):
    __tablename__ = "activation_tokens"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    token = Column(String, unique=True, index=True, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

    user = relationship("User", back_populates="activation_tokens")


class PasswordResetToken(Base):
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
    port = Column(Integer, nullable=True, default=45876)
    api_token = Column(String, unique=True, index=True, nullable=False)
    public_key = Column(String, nullable=True)
    os_info = Column(String, nullable=True)
    uptime_seconds = Column(Integer, nullable=True)
    is_online = Column(Boolean, default=False, nullable=False)
    last_seen_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

    # RBAC — the user who registered this host is its "host-admin" (owner).
    # They can share view-access with anyone else, and super-admin (User.is_admin)
    # can override everything.
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)

    owner = relationship("User", foreign_keys=[owner_id])
    metrics = relationship(
        "HostMetric", back_populates="host", cascade="all, delete-orphan"
    )
    access_grants = relationship(
        "HostAccess",
        back_populates="host",
        cascade="all, delete-orphan",
        foreign_keys="HostAccess.host_id",
    )


class HostAccess(Base):
    """A viewer-level grant: `user_id` can see the dashboard for `host_id`.

    Owner (`Host.owner_id`) and super-admin (`User.is_admin=True`) have
    implicit full access and don't need a row here. Grants are recorded
    only for OTHER users whom the owner/super-admin has shared with.

    Compound uniqueness: (host_id, user_id) — one row per pair.
    """

    __tablename__ = "host_access"
    id = Column(Integer, primary_key=True, index=True)
    host_id = Column(Integer, ForeignKey("hosts.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    granted_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    granted_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

    host = relationship("Host", back_populates="access_grants", foreign_keys=[host_id])
    user = relationship("User", foreign_keys=[user_id])
    granted_by = relationship("User", foreign_keys=[granted_by_id])

    __table_args__ = (
        UniqueConstraint("host_id", "user_id", name="uq_host_access_host_user"),
    )


class HostMetric(Base):
    __tablename__ = "host_metrics"
    id = Column(Integer, primary_key=True, index=True)
    host_id = Column(Integer, ForeignKey("hosts.id"))

    # Core host-level resource usage (%)
    cpu_percent = Column(Float, nullable=False)
    ram_percent = Column(Float, nullable=False)
    disk_percent = Column(Float, nullable=False)
    # NEW metrics
    inode_percent = Column(Float, nullable=True, default=0.0)
    disk_read_bytes_per_sec = Column(Float, nullable=True, default=0.0)
    disk_write_bytes_per_sec = Column(Float, nullable=True, default=0.0)
    net_external_rx_bps = Column(Float, nullable=True, default=0.0)
    net_external_tx_bps = Column(Float, nullable=True, default=0.0)
    net_internal_rx_bps = Column(Float, nullable=True, default=0.0)
    net_internal_tx_bps = Column(Float, nullable=True, default=0.0)

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
    """Audit log of authentication attempts."""

    __tablename__ = "login_logs"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    username_attempted = Column(String, nullable=True)
    ip_address = Column(String, nullable=False)
    status = Column(String, nullable=False)
    reason = Column(String, nullable=True)
    timestamp = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
