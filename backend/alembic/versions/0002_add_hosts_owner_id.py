"""add hosts.owner_id + host_access table (RBAC)

Revision ID: 0002_add_hosts_owner_id
Revises: 0001_baseline
Create Date: 2026-11-10

Fixes the live production error:
    sqlalchemy.exc.ProgrammingError:
      (psycopg.errors.UndefinedColumn) column hosts.owner_id does not exist

Root cause: the RBAC layer (host owners + shared access) was shipped
only in the SQLAlchemy models — ``Base.metadata.create_all()`` never
issues ``ALTER TABLE`` for columns added after the first boot, so the
``owner_id`` column was never physically added to databases that had
already been initialised against the pre-RBAC schema.

This revision:
  * adds ``hosts.owner_id`` (FK -> users.id, nullable) + index
  * creates the ``host_access`` association table with its composite
    UNIQUE(host_id, user_id) constraint

Both operations are guarded against pre-existing objects so the
migration is safe to re-apply after hand-fixing a DB.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0002_add_hosts_owner_id"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def _has_column(bind, table: str, column: str) -> bool:
    insp = sa.inspect(bind)
    return column in {c["name"] for c in insp.get_columns(table)}


def _has_table(bind, table: str) -> bool:
    return sa.inspect(bind).has_table(table)


def upgrade() -> None:
    bind = op.get_bind()

    # 1. hosts.owner_id
    if not _has_column(bind, "hosts", "owner_id"):
        op.add_column(
            "hosts",
            sa.Column("owner_id", sa.Integer(), nullable=True),
        )
        op.create_foreign_key(
            "fk_hosts_owner_id_users",
            source_table="hosts",
            referent_table="users",
            local_cols=["owner_id"],
            remote_cols=["id"],
            ondelete="SET NULL",
        )
        op.create_index("ix_hosts_owner_id", "hosts", ["owner_id"])

    # 2. host_access — RBAC grants
    if not _has_table(bind, "host_access"):
        op.create_table(
            "host_access",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "host_id",
                sa.Integer(),
                sa.ForeignKey("hosts.id"),
                nullable=False,
            ),
            sa.Column(
                "user_id",
                sa.Integer(),
                sa.ForeignKey("users.id"),
                nullable=False,
            ),
            sa.Column(
                "granted_by_id",
                sa.Integer(),
                sa.ForeignKey("users.id"),
                nullable=True,
            ),
            sa.Column(
                "granted_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.UniqueConstraint(
                "host_id", "user_id", name="uq_host_access_host_user"
            ),
        )
        op.create_index("ix_host_access_id", "host_access", ["id"])
        op.create_index("ix_host_access_host_id", "host_access", ["host_id"])
        op.create_index("ix_host_access_user_id", "host_access", ["user_id"])


def downgrade() -> None:
    bind = op.get_bind()
    if _has_table(bind, "host_access"):
        op.drop_index("ix_host_access_user_id", table_name="host_access")
        op.drop_index("ix_host_access_host_id", table_name="host_access")
        op.drop_index("ix_host_access_id", table_name="host_access")
        op.drop_table("host_access")
    if _has_column(bind, "hosts", "owner_id"):
        op.drop_index("ix_hosts_owner_id", table_name="hosts")
        op.drop_constraint("fk_hosts_owner_id_users", "hosts", type_="foreignkey")
        op.drop_column("hosts", "owner_id")
