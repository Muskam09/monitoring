"""baseline schema (pre-RBAC) — matches the hand-rolled create_all() DB

Revision ID: 0001_baseline
Revises:
Create Date: 2026-11-10

This revision describes the schema that existing deployments ALREADY
have (produced by ``Base.metadata.create_all`` on first boot — long
before Alembic was wired in). It is intentionally a no-op on an
existing database: fresh deployments execute it to build the tables,
and already-running deployments are `alembic stamp 0001_baseline`-ed
by the entrypoint so this migration is marked as applied without
re-running.

The NEXT revision (0002_add_hosts_owner_id) is what actually fixes
the live production error:
    column hosts.owner_id does not exist
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create every table that existed BEFORE we added owner_id.

    Guarded with ``IF NOT EXISTS`` semantics via an inspector check so
    the migration is idempotent against databases that were initialised
    by the legacy ``Base.metadata.create_all`` path.
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    if "users" not in existing:
        op.create_table(
            "users",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("username", sa.String(), nullable=False, unique=True),
            sa.Column("email", sa.String(), nullable=False, unique=True),
            sa.Column("password_hash", sa.String(), nullable=False),
            sa.Column(
                "role",
                sa.Enum("editor", "viewer", name="roleenum"),
                nullable=False,
                server_default="viewer",
            ),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("failed_login_attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
            sa.Column("is_locked", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("totp_secret", sa.String(), nullable=True),
            sa.Column("is_2fa_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_users_id", "users", ["id"])
        op.create_index("ix_users_username", "users", ["username"], unique=True)
        op.create_index("ix_users_email", "users", ["email"], unique=True)

    if "activation_tokens" not in existing:
        op.create_table(
            "activation_tokens",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("token", sa.String(), nullable=False, unique=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_activation_tokens_user_id", "activation_tokens", ["user_id"])
        op.create_index("ix_activation_tokens_token", "activation_tokens", ["token"], unique=True)

    if "password_reset_tokens" not in existing:
        op.create_table(
            "password_reset_tokens",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("token", sa.String(), nullable=False, unique=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_password_reset_tokens_user_id", "password_reset_tokens", ["user_id"])
        op.create_index("ix_password_reset_tokens_token", "password_reset_tokens", ["token"], unique=True)

    if "hosts" not in existing:
        op.create_table(
            "hosts",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("name", sa.String(), nullable=False, unique=True),
            sa.Column("ip_address", sa.String(), nullable=True),
            sa.Column("port", sa.Integer(), nullable=True, server_default="45876"),
            sa.Column("api_token", sa.String(), nullable=False, unique=True),
            sa.Column("public_key", sa.String(), nullable=True),
            sa.Column("os_info", sa.String(), nullable=True),
            sa.Column("uptime_seconds", sa.Integer(), nullable=True),
            sa.Column("is_online", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_hosts_id", "hosts", ["id"])
        op.create_index("ix_hosts_name", "hosts", ["name"], unique=True)
        op.create_index("ix_hosts_api_token", "hosts", ["api_token"], unique=True)

    if "host_metrics" not in existing:
        op.create_table(
            "host_metrics",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("host_id", sa.Integer(), sa.ForeignKey("hosts.id"), nullable=True),
            sa.Column("cpu_percent", sa.Float(), nullable=False),
            sa.Column("ram_percent", sa.Float(), nullable=False),
            sa.Column("disk_percent", sa.Float(), nullable=False),
            sa.Column("inode_percent", sa.Float(), nullable=True, server_default="0"),
            sa.Column("disk_read_bytes_per_sec", sa.Float(), nullable=True, server_default="0"),
            sa.Column("disk_write_bytes_per_sec", sa.Float(), nullable=True, server_default="0"),
            sa.Column("net_external_rx_bps", sa.Float(), nullable=True, server_default="0"),
            sa.Column("net_external_tx_bps", sa.Float(), nullable=True, server_default="0"),
            sa.Column("net_internal_rx_bps", sa.Float(), nullable=True, server_default="0"),
            sa.Column("net_internal_tx_bps", sa.Float(), nullable=True, server_default="0"),
            sa.Column("timestamp", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_host_metrics_id", "host_metrics", ["id"])
        op.create_index("ix_host_metrics_timestamp", "host_metrics", ["timestamp"])

    if "container_metrics" not in existing:
        op.create_table(
            "container_metrics",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("host_metric_id", sa.Integer(), sa.ForeignKey("host_metrics.id"), nullable=True),
            sa.Column("container_id", sa.String(), nullable=False),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("state", sa.String(), nullable=False),
            sa.Column("cpu_percent", sa.Float(), nullable=False),
            sa.Column("ram_percent", sa.Float(), nullable=False),
        )
        op.create_index("ix_container_metrics_id", "container_metrics", ["id"])

    if "login_logs" not in existing:
        op.create_table(
            "login_logs",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("username_attempted", sa.String(), nullable=True),
            sa.Column("ip_address", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("reason", sa.String(), nullable=True),
            sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_login_logs_id", "login_logs", ["id"])


def downgrade() -> None:
    # Full teardown. Only safe in dev/test.
    for t in (
        "login_logs",
        "container_metrics",
        "host_metrics",
        "hosts",
        "password_reset_tokens",
        "activation_tokens",
        "users",
    ):
        op.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
    op.execute("DROP TYPE IF EXISTS roleenum")
