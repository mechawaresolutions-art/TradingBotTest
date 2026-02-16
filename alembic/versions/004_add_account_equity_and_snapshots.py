"""Add account equity fields and account snapshots.

Revision ID: 004
Revises: 003
Create Date: 2026-02-16 15:50:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("accounts", schema=None) as batch_op:
        batch_op.add_column(sa.Column("equity", sa.Float(), nullable=False, server_default="0.0"))
        batch_op.add_column(sa.Column("margin_used", sa.Float(), nullable=False, server_default="0.0"))
        batch_op.add_column(sa.Column("free_margin", sa.Float(), nullable=False, server_default="0.0"))

    op.create_table(
        "account_snapshots",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("balance", sa.Float(), nullable=False),
        sa.Column("equity", sa.Float(), nullable=False),
        sa.Column("margin_used", sa.Float(), nullable=False),
        sa.Column("free_margin", sa.Float(), nullable=False),
        sa.Column("unrealized_pnl", sa.Float(), nullable=False, server_default="0.0"),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("account_id", "ts", name="uq_account_snapshot_ts"),
    )
    op.create_index("ix_account_snapshot_account_id", "account_snapshots", ["account_id"])
    op.create_index("ix_account_snapshot_ts", "account_snapshots", ["ts"])


def downgrade() -> None:
    op.drop_index("ix_account_snapshot_ts", table_name="account_snapshots")
    op.drop_index("ix_account_snapshot_account_id", table_name="account_snapshots")
    op.drop_table("account_snapshots")

    with op.batch_alter_table("accounts", schema=None) as batch_op:
        batch_op.drop_column("free_margin")
        batch_op.drop_column("margin_used")
        batch_op.drop_column("equity")
