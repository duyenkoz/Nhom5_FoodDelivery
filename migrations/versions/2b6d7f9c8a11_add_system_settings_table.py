"""Add system settings table.

Revision ID: 2b6d7f9c8a11
Revises: b7a3c9d2e4f1
Create Date: 2026-04-22 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "2b6d7f9c8a11"
down_revision = "b7a3c9d2e4f1"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "system_settings",
        sa.Column("setting_key", sa.String(length=100), nullable=False),
        sa.Column("setting_value", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.PrimaryKeyConstraint("setting_key"),
    )


def downgrade():
    op.drop_table("system_settings")
