"""add_paper_trade_broker_profile

Revision ID: c7a4f2b19d30
Revises: 9d1f3b8e4a2c
Create Date: 2026-11-23 00:00:00.000000

Stores the BrokerSpec profile name on each paper position/trade record.
Nullable: legacy rows without the field remain valid.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c7a4f2b19d30'
down_revision: Union[str, Sequence[str], None] = '9d1f3b8e4a2c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'paper_trades',
        sa.Column('broker_profile', sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('paper_trades', 'broker_profile')
