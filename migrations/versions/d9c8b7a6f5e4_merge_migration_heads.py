"""Merge migration heads.

Revision ID: d9c8b7a6f5e4
Revises: 1a2b3c4d5e6f, a2f6c1b9d4e8
Create Date: 2026-04-11 00:00:00.000000
"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "d9c8b7a6f5e4"
down_revision = ("1a2b3c4d5e6f", "a2f6c1b9d4e8")
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
