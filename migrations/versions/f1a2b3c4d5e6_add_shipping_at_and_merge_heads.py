"""add shipping_at and merge heads

Revision ID: f1a2b3c4d5e6
Revises: 9c1d7e8b4f2a, b7a3c9d2e4f1
Create Date: 2026-04-21 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "f1a2b3c4d5e6"
down_revision = ("9c1d7e8b4f2a", "b7a3c9d2e4f1")
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("orders") as batch_op:
        batch_op.add_column(sa.Column("shipping_at", sa.DateTime(), nullable=True))


def downgrade():
    with op.batch_alter_table("orders") as batch_op:
        batch_op.drop_column("shipping_at")
