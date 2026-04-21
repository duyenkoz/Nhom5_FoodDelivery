"""add cancel reason to orders

Revision ID: 9c1d7e8b4f2a
Revises: 3f4d5e6a7b8c
Create Date: 2026-04-20 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "9c1d7e8b4f2a"
down_revision = "3f4d5e6a7b8c"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("orders", schema=None) as batch_op:
        batch_op.add_column(sa.Column("cancel_reason", sa.String(length=300), nullable=True))


def downgrade():
    with op.batch_alter_table("orders", schema=None) as batch_op:
        batch_op.drop_column("cancel_reason")
