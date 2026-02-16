"""Add Macro 7 accounting tables and fill accounting marker.

Revision ID: 006
Revises: 005
Create Date: 2026-02-16 19:10:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("fills", schema=None) as batch_op:
        batch_op.add_column(sa.Column("accounted_at_open_time", sa.DateTime(timezone=True), nullable=True))

    op.create_index("ix_fills_accounted_at_open_time", "fills", ["accounted_at_open_time"])

    op.create_table(
        "accounting_positions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.String(length=20), nullable=False),
        sa.Column("net_qty", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("avg_entry_price", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("updated_open_time", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("account_id", "symbol", name="uq_accounting_position_account_symbol"),
    )

    op.create_table(
        "accounting_snapshots",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("asof_open_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("balance", sa.Float(), nullable=False),
        sa.Column("equity", sa.Float(), nullable=False),
        sa.Column("unrealized_pnl", sa.Float(), nullable=False),
        sa.Column("margin_used", sa.Float(), nullable=False),
        sa.Column("free_margin", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("account_id", "asof_open_time", name="uq_accounting_snapshot_account_asof"),
    )
    op.create_index("ix_accounting_snapshot_asof", "accounting_snapshots", ["asof_open_time"])

    op.create_table(
        "realized_trades",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.String(length=20), nullable=False),
        sa.Column("open_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_qty", sa.Float(), nullable=False),
        sa.Column("entry_price", sa.Float(), nullable=False),
        sa.Column("exit_price", sa.Float(), nullable=False),
        sa.Column("realized_pnl", sa.Float(), nullable=False),
        sa.Column("fill_id", sa.Integer(), nullable=True),
        sa.Column("order_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["fill_id"], ["fills.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_realized_trades_account_time", "realized_trades", ["account_id", "open_time"])


def downgrade() -> None:
    op.drop_index("ix_realized_trades_account_time", table_name="realized_trades")
    op.drop_table("realized_trades")

    op.drop_index("ix_accounting_snapshot_asof", table_name="accounting_snapshots")
    op.drop_table("accounting_snapshots")

    op.drop_table("accounting_positions")

    op.drop_index("ix_fills_accounted_at_open_time", table_name="fills")
    with op.batch_alter_table("fills", schema=None) as batch_op:
        batch_op.drop_column("accounted_at_open_time")
