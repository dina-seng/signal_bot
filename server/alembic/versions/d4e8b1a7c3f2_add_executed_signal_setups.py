"""Add executed_signal_setups lifecycle ledger.

Revision ID: d4e8b1a7c3f2
Revises: 9d1f3b8e4a2c
Create Date: 2026-11-26
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d4e8b1a7c3f2"
down_revision: Union[str, Sequence[str], None] = "9d1f3b8e4a2c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "executed_signal_setups" in inspector.get_table_names():
        return

    op.create_table(
        "executed_signal_setups",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.String(20), nullable=False),
        sa.Column("timeframe", sa.String(10), nullable=False),
        sa.Column("candle_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("direction", sa.String(10), nullable=False),
        sa.Column("signal_id", sa.Integer(), nullable=True),
        sa.Column("trade_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="EXECUTED"),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "symbol",
            "timeframe",
            "candle_timestamp",
            "direction",
            name="uq_executed_signal_setup",
        ),
    )
    op.create_index(
        "ix_executed_setup_status",
        "executed_signal_setups",
        ["status", "executed_at"],
    )
    op.create_index(
        "ix_executed_signal_setups_signal_id",
        "executed_signal_setups",
        ["signal_id"],
    )
    op.create_index(
        "ix_executed_signal_setups_trade_id",
        "executed_signal_setups",
        ["trade_id"],
    )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "executed_signal_setups" in inspector.get_table_names():
        op.drop_table("executed_signal_setups")
