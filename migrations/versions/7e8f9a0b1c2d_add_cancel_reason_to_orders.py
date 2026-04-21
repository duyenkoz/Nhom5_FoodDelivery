"""Add cancel_reason to orders.

Revision ID: 7e8f9a0b1c2d
Revises: d9c8b7a6f5e4
Create Date: 2026-04-21 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "7e8f9a0b1c2d"
down_revision = "d9c8b7a6f5e4"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("orders", sa.Column("cancel_reason", sa.String(length=300), nullable=True))


def downgrade():
    op.drop_column("orders", "cancel_reason")
