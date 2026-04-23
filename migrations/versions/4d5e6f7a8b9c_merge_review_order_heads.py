"""Merge current migration heads.

Revision ID: 4d5e6f7a8b9c
Revises: 2b6d7f9c8a11, a0feee8713a9, c1d2e3f4a5b6, 2c3d4e5f6a7b
Create Date: 2026-04-23 00:00:00.000000
"""

from alembic import op


revision = "4d5e6f7a8b9c"
down_revision = ("2b6d7f9c8a11", "a0feee8713a9", "c1d2e3f4a5b6", "2c3d4e5f6a7b")
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
