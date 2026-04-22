"""add note to cartitems

Revision ID: a0feee8713a9
Revises: c972b0759dfc
Create Date: 2026-04-22 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "a0feee8713a9"
down_revision = "c972b0759dfc"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("cartitems")}
    if "note" not in columns:
        op.add_column("cartitems", sa.Column("note", sa.String(255), nullable=True))


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("cartitems")}
    if "note" in columns:
        op.drop_column("cartitems", "note")
