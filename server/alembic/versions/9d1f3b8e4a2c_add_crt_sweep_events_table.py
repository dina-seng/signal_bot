"""add_crt_sweep_events_table

Revision ID: 9d1f3b8e4a2c
Revises: 8c3fca88f849
Create Date: 2026-11-16 22:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = '9d1f3b8e4a2c'
down_revision: Union[str, Sequence[str], None] = '8c3fca88f849'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema to add crt_sweep_events table (idempotent)."""
    bind = op.get_bind()
    
    # 1. Check if table exists before creating
    if not bind.dialect.has_table(bind, 'crt_sweep_events'):
        op.create_table(
            'crt_sweep_events',
            sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
            sa.Column('sweep_key', sa.String(length=255), nullable=False),
            sa.Column('symbol', sa.String(length=20), nullable=False),
            sa.Column('timeframe', sa.String(length=10), nullable=False),
            sa.Column('direction', sa.String(length=10), nullable=False),
            sa.Column('current_state', sa.String(length=30), nullable=False, server_default='POTENTIAL'),
            sa.Column('quality_tier', sa.String(length=10), nullable=True),
            sa.Column('last_alerted_state', sa.String(length=30), nullable=True),
            sa.Column('entry_price', sa.Float(), nullable=True),
            sa.Column('stop_loss', sa.Float(), nullable=True),
            sa.Column('take_profit_1', sa.Float(), nullable=True),
            sa.Column('take_profit_2', sa.Float(), nullable=True),
            sa.Column('zone_high', sa.Float(), nullable=True),
            sa.Column('zone_low', sa.Float(), nullable=True),
            sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('emitted_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('cooldown_until', sa.DateTime(timezone=True), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint('id'),
        )
        
        # 2. Only create indexes if the table was just created
        op.create_index(op.f('ix_crt_sweep_events_id'), 'crt_sweep_events', ['id'], unique=False)
        op.create_index(op.f('ix_crt_sweep_events_sweep_key'), 'crt_sweep_events', ['sweep_key'], unique=True)
        op.create_index(op.f('ix_crt_sweep_events_symbol'), 'crt_sweep_events', ['symbol'], unique=False)
        op.create_index(op.f('ix_crt_sweep_events_current_state'), 'crt_sweep_events', ['current_state'], unique=False)
        op.create_index(op.f('ix_crt_sweep_events_cooldown_until'), 'crt_sweep_events', ['cooldown_until'], unique=False)
        op.create_index('ix_crt_sweep_key_cooldown', 'crt_sweep_events', ['sweep_key', 'cooldown_until'], unique=False)
        op.create_index('ix_crt_sweep_state', 'crt_sweep_events', ['symbol', 'current_state'], unique=False)
    else:
        print("✅ Table 'crt_sweep_events' already exists, skipping creation safely.")

def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_crt_sweep_state', table_name='crt_sweep_events')
    op.drop_index('ix_crt_sweep_key_cooldown', table_name='crt_sweep_events')
    op.drop_index(op.f('ix_crt_sweep_events_cooldown_until'), table_name='crt_sweep_events')
    op.drop_index(op.f('ix_crt_sweep_events_current_state'), table_name='crt_sweep_events')
    op.drop_index(op.f('ix_crt_sweep_events_symbol'), table_name='crt_sweep_events')
    op.drop_index(op.f('ix_crt_sweep_events_sweep_key'), table_name='crt_sweep_events')
    op.drop_index(op.f('ix_crt_sweep_events_id'), table_name='crt_sweep_events')
    op.drop_table('crt_sweep_events')

