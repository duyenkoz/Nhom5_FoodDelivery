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
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("orders")}
    if "cancel_reason" not in columns:
        op.add_column("orders", sa.Column("cancel_reason", sa.String(length=300), nullable=True))


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("orders")}
    if "cancel_reason" in columns:
        op.drop_column("orders", "cancel_reason")
