"""Add order linkage to reviews

Revision ID: 2c3d4e5f6a7b
Revises: f1a2b3c4d5e6
Create Date: 2026-04-23 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "2c3d4e5f6a7b"
down_revision = "f1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("reviews", schema=None) as batch_op:
        batch_op.add_column(sa.Column("order_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key("fk_reviews_order_id_orders", "orders", ["order_id"], ["order_id"])
        batch_op.create_index(batch_op.f("uq_reviews_order_id"), ["order_id"], unique=True)


def downgrade():
    with op.batch_alter_table("reviews", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("uq_reviews_order_id"))
        batch_op.drop_constraint("fk_reviews_order_id_orders", type_="foreignkey")
        batch_op.drop_column("order_id")
