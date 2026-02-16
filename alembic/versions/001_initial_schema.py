"""Initial schema: candles, accounts, orders, fills, positions, trades with indexes.

Revision ID: 001
Revises: 
Create Date: 2026-02-16 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create candles table
    op.create_table(
        'candles',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('symbol', sa.String(20), nullable=False),
        sa.Column('timeframe', sa.String(10), nullable=False),
        sa.Column('open_time', sa.DateTime(timezone=True), nullable=False),
        sa.Column('open', sa.Float(), nullable=False),
        sa.Column('high', sa.Float(), nullable=False),
        sa.Column('low', sa.Float(), nullable=False),
        sa.Column('close', sa.Float(), nullable=False),
        sa.Column('volume', sa.Float(), nullable=True),
        sa.Column('source', sa.String(50), nullable=False, server_default='provider'),
        sa.Column('ingested_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('symbol', 'timeframe', 'open_time', name='uq_candle_time'),
        sa.CheckConstraint('high >= low', name='ck_high_gte_low'),
        sa.CheckConstraint('high >= open', name='ck_high_gte_open'),
        sa.CheckConstraint('high >= close', name='ck_high_gte_close'),
        sa.CheckConstraint('low <= open', name='ck_low_lte_open'),
        sa.CheckConstraint('low <= close', name='ck_low_lte_close'),
    )
    op.create_index('ix_candle_symbol', 'candles', ['symbol'])
    op.create_index('ix_candle_timeframe', 'candles', ['timeframe'])
    op.create_index('ix_candle_open_time', 'candles', ['open_time'])
    op.create_index('ix_candle_lookup', 'candles', ['symbol', 'timeframe', 'open_time'], unique=False)

    # Create accounts table
    op.create_table(
        'accounts',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('balance', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('currency', sa.String(10), nullable=False, server_default='USD'),
        sa.Column('leverage', sa.Float(), nullable=False, server_default='1.0'),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_account_updated', 'accounts', ['updated_at'])

    # Create orders table
    op.create_table(
        'orders',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('ts', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('symbol', sa.String(20), nullable=False),
        sa.Column('side', sa.String(4), nullable=False),
        sa.Column('type', sa.String(20), nullable=False, server_default='market'),
        sa.Column('qty', sa.Float(), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='filled'),
        sa.Column('reason', sa.String(255), nullable=True),
        sa.Column('requested_price', sa.Float(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_orders_ts', 'orders', ['ts'])
    op.create_index('ix_orders_status', 'orders', ['status'])

    # Create fills table
    op.create_table(
        'fills',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('order_id', sa.Integer(), nullable=False),
        sa.Column('ts', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('symbol', sa.String(20), nullable=False),
        sa.Column('side', sa.String(4), nullable=False),
        sa.Column('qty', sa.Float(), nullable=False),
        sa.Column('price', sa.Float(), nullable=False),
        sa.Column('fee', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('slippage', sa.Float(), nullable=False, server_default='0.0'),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['order_id'], ['orders.id'], ondelete='CASCADE'),
    )
    op.create_index('ix_fills_order_id', 'fills', ['order_id'])
    op.create_index('ix_fills_ts', 'fills', ['ts'])

    # Create positions table
    op.create_table(
        'positions',
        sa.Column('symbol', sa.String(20), nullable=False),
        sa.Column('qty_signed', sa.Float(), nullable=False),
        sa.Column('avg_price', sa.Float(), nullable=False),
        sa.Column('opened_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('stop_loss', sa.Float(), nullable=True),
        sa.Column('take_profit', sa.Float(), nullable=True),
        sa.Column('realized_pnl', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('entry_order_id', sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint('symbol'),
        sa.ForeignKeyConstraint(['entry_order_id'], ['orders.id'], ondelete='SET NULL'),
    )
    op.create_index('ix_position_symbol', 'positions', ['symbol'])

    # Create trades table
    op.create_table(
        'trades',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('entry_ts', sa.DateTime(timezone=True), nullable=False),
        sa.Column('exit_ts', sa.DateTime(timezone=True), nullable=False),
        sa.Column('symbol', sa.String(20), nullable=False),
        sa.Column('qty', sa.Float(), nullable=False),
        sa.Column('entry_price', sa.Float(), nullable=False),
        sa.Column('exit_price', sa.Float(), nullable=False),
        sa.Column('pnl', sa.Float(), nullable=False),
        sa.Column('exit_reason', sa.String(50), nullable=True),
        sa.Column('entry_order_id', sa.Integer(), nullable=True),
        sa.Column('exit_order_id', sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['entry_order_id'], ['orders.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['exit_order_id'], ['orders.id'], ondelete='SET NULL'),
    )
    op.create_index('ix_trades_entry_ts', 'trades', ['entry_ts'])
    op.create_index('ix_trades_exit_ts', 'trades', ['exit_ts'])


def downgrade() -> None:
    op.drop_index('ix_trades_exit_ts', table_name='trades')
    op.drop_index('ix_trades_entry_ts', table_name='trades')
    op.drop_table('trades')
    
    op.drop_index('ix_position_symbol', table_name='positions')
    op.drop_table('positions')
    
    op.drop_index('ix_fills_ts', table_name='fills')
    op.drop_index('ix_fills_order_id', table_name='fills')
    op.drop_table('fills')
    
    op.drop_index('ix_orders_status', table_name='orders')
    op.drop_index('ix_orders_ts', table_name='orders')
    op.drop_table('orders')
    
    op.drop_index('ix_account_updated', table_name='accounts')
    op.drop_table('accounts')
    
    op.drop_index('ix_candle_lookup', table_name='candles')
    op.drop_index('ix_candle_open_time', table_name='candles')
    op.drop_index('ix_candle_timeframe', table_name='candles')
    op.drop_index('ix_candle_symbol', table_name='candles')
    op.drop_table('candles')
