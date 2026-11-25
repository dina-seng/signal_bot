"""Add composite indexes used by the dashboard snapshot queries.

Revision ID: 3f6a1c9d2b4e
Revises: c7a4f2b19d30
Create Date: 2026-11-25
"""

from alembic import op
import sqlalchemy as sa


revision = "3f6a1c9d2b4e"
down_revision = "c7a4f2b19d30"
branch_labels = None
depends_on = None


# (index name, table, columns) — the first three already ship with the initial
# schema; the guard makes this migration safe on databases created without them.
INDEXES = (
    ("ix_candle_query", "candles", ("symbol", "timeframe", "timestamp")),
    ("ix_structure_symbol_tf", "structure_events", ("symbol", "timeframe", "timestamp")),
    ("ix_liquidity_symbol_tf", "liquidity_events", ("symbol", "timeframe", "timestamp")),
    ("ix_paper_trade_account_status", "paper_trades", ("account_id", "status")),
)


def _existing_indexes(table: str) -> set:
    inspector = sa.inspect(op.get_bind())
    if table not in inspector.get_table_names():
        return set()
    return {idx["name"] for idx in inspector.get_indexes(table) if idx.get("name")}


def upgrade() -> None:
    for name, table, columns in INDEXES:
        if name in _existing_indexes(table):
            continue
        op.create_index(name, table, list(columns), unique=False)


def downgrade() -> None:
    # Only remove the index introduced by this revision. The other three predate
    # it and must survive a rollback.
    name, table, _ = INDEXES[-1]
    if name in _existing_indexes(table):
        op.drop_index(name, table_name=table)
