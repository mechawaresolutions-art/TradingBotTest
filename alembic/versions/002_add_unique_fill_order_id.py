"""Add unique constraint on fills.order_id.

Revision ID: 002
Revises: 001
Create Date: 2026-02-16 14:40:00.000000

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("fills", schema=None) as batch_op:
        batch_op.create_unique_constraint("uq_fills_order_id", ["order_id"])


def downgrade() -> None:
    with op.batch_alter_table("fills", schema=None) as batch_op:
        batch_op.drop_constraint("uq_fills_order_id", type_="unique")
