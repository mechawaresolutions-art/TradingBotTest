"""Add idempotency key to orders.

Revision ID: 003
Revises: 002
Create Date: 2026-02-16 15:10:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("orders", schema=None) as batch_op:
        batch_op.add_column(sa.Column("idempotency_key", sa.String(length=128), nullable=True))
        batch_op.create_unique_constraint("uq_orders_idempotency_key", ["idempotency_key"])


def downgrade() -> None:
    with op.batch_alter_table("orders", schema=None) as batch_op:
        batch_op.drop_constraint("uq_orders_idempotency_key", type_="unique")
        batch_op.drop_column("idempotency_key")
