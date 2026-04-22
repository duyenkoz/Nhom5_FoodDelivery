"""Add report fields to reviews

Revision ID: 1a2b3c4d5e6f
Revises: 6b1f9d2c4a10
Create Date: 2026-04-10 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


revision = "1a2b3c4d5e6f"
down_revision = "6b1f9d2c4a10"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("reviews", schema=None) as batch_op:
        batch_op.add_column(sa.Column("report_status", sa.String(length=20), nullable=False, server_default="none"))
        batch_op.add_column(sa.Column("report_reason", sa.String(length=300), nullable=True))
        batch_op.add_column(sa.Column("report_date", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("report_handled_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("report_admin_action", sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column("report_admin_note", sa.String(length=300), nullable=True))
        batch_op.add_column(sa.Column("report_handled_by", sa.Integer(), nullable=True))
        batch_op.create_foreign_key("fk_reviews_report_handled_by_users", "users", ["report_handled_by"], ["user_id"])

    with op.batch_alter_table("reviews", schema=None) as batch_op:
        batch_op.alter_column("report_status", server_default=None)


def downgrade():
    with op.batch_alter_table("reviews", schema=None) as batch_op:
        batch_op.drop_constraint("fk_reviews_report_handled_by_users", type_="foreignkey")
        batch_op.drop_column("report_handled_by")
        batch_op.drop_column("report_admin_note")
        batch_op.drop_column("report_admin_action")
        batch_op.drop_column("report_handled_at")
        batch_op.drop_column("report_date")
        batch_op.drop_column("report_reason")
        batch_op.drop_column("report_status")
