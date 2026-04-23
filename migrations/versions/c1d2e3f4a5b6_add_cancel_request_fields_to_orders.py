"""add cancel request fields to orders

Revision ID: c1d2e3f4a5b6
Revises: f1a2b3c4d5e6
Create Date: 2026-04-22 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "c1d2e3f4a5b6"
down_revision = "f1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("orders") as batch_op:
        batch_op.add_column(sa.Column("cancel_request_status", sa.String(length=30), nullable=True))
        batch_op.add_column(sa.Column("cancel_request_reason", sa.String(length=300), nullable=True))
        batch_op.add_column(sa.Column("cancel_request_date", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("cancel_request_handled_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("cancel_request_handled_by", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_orders_cancel_request_handled_by_users",
            "users",
            ["cancel_request_handled_by"],
            ["user_id"],
        )
        batch_op.add_column(sa.Column("cancel_request_admin_note", sa.String(length=300), nullable=True))


def downgrade():
    with op.batch_alter_table("orders") as batch_op:
        batch_op.drop_constraint("fk_orders_cancel_request_handled_by_users", type_="foreignkey")
        batch_op.drop_column("cancel_request_admin_note")
        batch_op.drop_column("cancel_request_handled_by")
        batch_op.drop_column("cancel_request_handled_at")
        batch_op.drop_column("cancel_request_date")
        batch_op.drop_column("cancel_request_reason")
        batch_op.drop_column("cancel_request_status")
