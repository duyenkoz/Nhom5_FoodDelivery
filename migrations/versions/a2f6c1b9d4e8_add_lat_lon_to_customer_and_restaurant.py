"""Add latitude and longitude to customer and restaurant profiles.

Revision ID: a2f6c1b9d4e8
Revises: e051f0abe776
Create Date: 2026-04-10 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "a2f6c1b9d4e8"
down_revision = "e051f0abe776"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("customers", schema=None) as batch_op:
        batch_op.add_column(sa.Column("latitude", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("longitude", sa.Float(), nullable=True))

    with op.batch_alter_table("restaurants", schema=None) as batch_op:
        batch_op.add_column(sa.Column("latitude", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("longitude", sa.Float(), nullable=True))


def downgrade():
    with op.batch_alter_table("restaurants", schema=None) as batch_op:
        batch_op.drop_column("longitude")
        batch_op.drop_column("latitude")

    with op.batch_alter_table("customers", schema=None) as batch_op:
        batch_op.drop_column("longitude")
        batch_op.drop_column("latitude")
