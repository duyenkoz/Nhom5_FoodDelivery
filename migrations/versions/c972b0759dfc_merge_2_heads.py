"""merge 2 heads

Revision ID: c972b0759dfc
Revises: 9c1d7e8b4f2a, b7a3c9d2e4f1
Create Date: 2026-04-22 11:26:15.165722

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c972b0759dfc'
down_revision = ('9c1d7e8b4f2a', 'b7a3c9d2e4f1')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
