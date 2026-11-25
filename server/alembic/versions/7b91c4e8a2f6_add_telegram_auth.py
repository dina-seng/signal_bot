"""Add Telegram users, login tokens and nullable user links (Milestone 2).

Revision ID: 7b91c4e8a2f6
Revises: 3f6a1c9d2b4e
Create Date: 2026-11-25
"""

from alembic import op
import sqlalchemy as sa


revision = "7b91c4e8a2f6"
down_revision = "3f6a1c9d2b4e"
branch_labels = None
depends_on = None


def _columns(table: str) -> set:
    inspector = sa.inspect(op.get_bind())
    if table not in inspector.get_table_names():
        return set()
    return {column["name"] for column in inspector.get_columns(table)}


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())

    if "users" not in tables:
        op.create_table(
            "users",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("telegram_id", sa.BigInteger(), nullable=True),
            sa.Column("username", sa.String(length=255), nullable=True),
            sa.Column("first_name", sa.String(length=255), nullable=True),
            sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("telegram_id", name="uq_users_telegram_id"),
        )
        op.create_index("ix_users_telegram_id", "users", ["telegram_id"], unique=True)

    if "login_tokens" not in tables:
        op.create_table(
            "login_tokens",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("token_hash", sa.String(length=64), nullable=False),
            sa.Column("telegram_id", sa.BigInteger(), nullable=False),
            sa.Column("username", sa.String(length=255), nullable=True),
            sa.Column("first_name", sa.String(length=255), nullable=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("token_hash", name="uq_login_tokens_token_hash"),
        )
        op.create_index("ix_login_tokens_token_hash", "login_tokens", ["token_hash"], unique=True)
        op.create_index("ix_login_tokens_telegram_id", "login_tokens", ["telegram_id"])

    for table in ("virtual_accounts", "paper_trades"):
        if "user_id" not in _columns(table):
            op.add_column(
                table,
                sa.Column(
                    "user_id",
                    sa.Uuid(),
                    sa.ForeignKey("users.id", ondelete="SET NULL"),
                    nullable=True,
                ),
            )
            op.create_index(f"ix_{table}_user_id", table, ["user_id"])


def downgrade() -> None:
    for table in ("paper_trades", "virtual_accounts"):
        if "user_id" in _columns(table):
            op.drop_index(f"ix_{table}_user_id", table_name=table)
            op.drop_column(table, "user_id")
    op.drop_table("login_tokens")
    op.drop_table("users")
