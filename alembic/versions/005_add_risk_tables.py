"""Add risk limits and daily equity tables.

Revision ID: 005
Revises: 004
Create Date: 2026-02-16 18:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "risk_limits",
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("max_open_positions", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("max_open_positions_per_symbol", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("max_total_notional", sa.Float(), nullable=False, server_default="1000000"),
        sa.Column("max_symbol_notional", sa.Float(), nullable=False, server_default="500000"),
        sa.Column("risk_per_trade_pct", sa.Float(), nullable=False, server_default="0.01"),
        sa.Column("daily_loss_limit_pct", sa.Float(), nullable=False, server_default="0.05"),
        sa.Column("daily_loss_limit_amount", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("leverage", sa.Float(), nullable=False, server_default="30"),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("account_id"),
    )

    op.create_table(
        "daily_equity",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("day_start_equity", sa.Float(), nullable=False),
        sa.Column("min_equity", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("account_id", "day", name="uq_daily_equity_account_day"),
    )
    op.create_index("ix_daily_equity_account_id", "daily_equity", ["account_id"])
    op.create_index("ix_daily_equity_day", "daily_equity", ["day"])


def downgrade() -> None:
    op.drop_index("ix_daily_equity_day", table_name="daily_equity")
    op.drop_index("ix_daily_equity_account_id", table_name="daily_equity")
    op.drop_table("daily_equity")
    op.drop_table("risk_limits")
