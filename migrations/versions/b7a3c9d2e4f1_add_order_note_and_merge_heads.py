"""Add note to orders.

Revision ID: b7a3c9d2e4f1
Revises: 54935e114134
Create Date: 2026-04-21 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "b7a3c9d2e4f1"
down_revision = "54935e114134"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("orders", sa.Column("note", sa.String(length=300), nullable=True))


def downgrade():
    op.drop_column("orders", "note")
