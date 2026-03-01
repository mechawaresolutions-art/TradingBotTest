"""Add Macro 9 orchestrator run reports table.

Revision ID: 007
Revises: 006
Create Date: 2026-03-01 00:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "run_reports",
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("symbol", sa.String(length=20), nullable=False),
        sa.Column("timeframe", sa.String(length=10), nullable=False),
        sa.Column("candle_ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("intent_json", sa.JSON(), nullable=True),
        sa.Column("risk_json", sa.JSON(), nullable=True),
        sa.Column("order_json", sa.JSON(), nullable=True),
        sa.Column("fill_json", sa.JSON(), nullable=True),
        sa.Column("positions_json", sa.JSON(), nullable=True),
        sa.Column("account_json", sa.JSON(), nullable=True),
        sa.Column("summary_text", sa.Text(), nullable=False),
        sa.Column("telegram_text", sa.Text(), nullable=False),
        sa.Column("error_text", sa.Text(), nullable=True),
        sa.Column("mode", sa.String(length=20), nullable=False),
        sa.PrimaryKeyConstraint("run_id"),
        sa.UniqueConstraint("symbol", "timeframe", "candle_ts", name="uq_run_reports_symbol_tf_ts"),
    )
    op.create_index("ix_run_reports_candle_ts", "run_reports", ["candle_ts"])
    op.create_index("ix_run_reports_status", "run_reports", ["status"])


def downgrade() -> None:
    op.drop_index("ix_run_reports_status", table_name="run_reports")
    op.drop_index("ix_run_reports_candle_ts", table_name="run_reports")
    op.drop_table("run_reports")
