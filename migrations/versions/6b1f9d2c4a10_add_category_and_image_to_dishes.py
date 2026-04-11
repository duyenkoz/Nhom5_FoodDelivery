"""Add category and image to dishes

Revision ID: 6b1f9d2c4a10
Revises: e051f0abe776
Create Date: 2026-04-10 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "6b1f9d2c4a10"
down_revision = "e051f0abe776"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("dishes", schema=None) as batch_op:
        batch_op.add_column(sa.Column("category", sa.String(length=80), nullable=True))
        batch_op.add_column(sa.Column("image", sa.String(length=255), nullable=True))


def downgrade():
    with op.batch_alter_table("dishes", schema=None) as batch_op:
        batch_op.drop_column("image")
        batch_op.drop_column("category")
