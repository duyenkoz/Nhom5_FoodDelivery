"""add note to orderitems

Revision ID: 7d2a4c9f1b11
Revises: d9c8b7a6f5e4
Create Date: 2026-04-13 00:00:00.000000
"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "7d2a4c9f1b11"
down_revision = "d9c8b7a6f5e4"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE orderitems ADD COLUMN note VARCHAR(300) NULL")


def downgrade():
    op.execute("ALTER TABLE orderitems DROP COLUMN note")
