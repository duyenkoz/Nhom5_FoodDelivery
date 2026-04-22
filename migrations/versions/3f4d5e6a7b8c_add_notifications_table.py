"""add notifications table

Revision ID: 3f4d5e6a7b8c
Revises: 7d2a4c9f1b11
Create Date: 2026-04-20 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = "3f4d5e6a7b8c"
down_revision = "7d2a4c9f1b11"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)

    if not inspector.has_table("notifications"):
        op.create_table(
            "notifications",
            sa.Column("notification_id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("type", sa.String(length=50), nullable=True),
            sa.Column("title", sa.String(length=120), nullable=False),
            sa.Column("message", sa.String(length=255), nullable=False),
            sa.Column("link", sa.String(length=255), nullable=True),
            sa.Column("payload_json", sa.Text(), nullable=True),
            sa.Column("is_read", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.user_id"]),
            sa.PrimaryKeyConstraint("notification_id"),
        )

    existing_indexes = {index["name"] for index in inspector.get_indexes("notifications")} if inspector.has_table("notifications") else set()
    index_name = "ix_notifications_user_id"
    if index_name not in existing_indexes and inspector.has_table("notifications"):
        op.create_index(index_name, "notifications", ["user_id"], unique=False)


def downgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    if inspector.has_table("notifications"):
        existing_indexes = {index["name"] for index in inspector.get_indexes("notifications")}
        if "ix_notifications_user_id" in existing_indexes:
            op.drop_index("ix_notifications_user_id", table_name="notifications")
        op.drop_table("notifications")
