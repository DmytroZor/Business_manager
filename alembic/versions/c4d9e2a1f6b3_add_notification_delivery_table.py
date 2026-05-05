"""add notification delivery table

Revision ID: c4d9e2a1f6b3
Revises: b7f2c1d9e4a1
Create Date: 2026-04-29 13:30:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "c4d9e2a1f6b3"
down_revision: Union[str, Sequence[str], None] = "b7f2c1d9e4a1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


notificationchannel = postgresql.ENUM(
    "TELEGRAM",
    name="notificationchannel",
    create_type=False,
)

notificationdeliverystatus = postgresql.ENUM(
    "PENDING",
    "PROCESSING",
    "SENT",
    "FAILED",
    name="notificationdeliverystatus",
    create_type=False,
)

userrole = postgresql.ENUM(
    "CUSTOMER",
    "COURIER",
    "ADMIN",
    name="userrole",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    notificationchannel.create(bind, checkfirst=True)
    notificationdeliverystatus.create(bind, checkfirst=True)

    op.create_table(
        "notification_delivery",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("channel", notificationchannel, nullable=False),
        sa.Column("status", notificationdeliverystatus, nullable=False),
        sa.Column("recipient_role", userrole, nullable=True),
        sa.Column("recipient_user_id", sa.Integer(), nullable=True),
        sa.Column("telegram_chat_id", sa.String(length=100), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=True),
        sa.Column("delivery_id", sa.Integer(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("processing_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["delivery_id"], ["delivery.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["recipient_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_notification_delivery_channel"), "notification_delivery", ["channel"], unique=False)
    op.create_index(op.f("ix_notification_delivery_delivery_id"), "notification_delivery", ["delivery_id"], unique=False)
    op.create_index(op.f("ix_notification_delivery_event_type"), "notification_delivery", ["event_type"], unique=False)
    op.create_index(op.f("ix_notification_delivery_order_id"), "notification_delivery", ["order_id"], unique=False)
    op.create_index(
        op.f("ix_notification_delivery_recipient_role"),
        "notification_delivery",
        ["recipient_role"],
        unique=False,
    )
    op.create_index(
        op.f("ix_notification_delivery_recipient_user_id"),
        "notification_delivery",
        ["recipient_user_id"],
        unique=False,
    )
    op.create_index(op.f("ix_notification_delivery_status"), "notification_delivery", ["status"], unique=False)
    op.create_index(
        op.f("ix_notification_delivery_telegram_chat_id"),
        "notification_delivery",
        ["telegram_chat_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_notification_delivery_telegram_chat_id"), table_name="notification_delivery")
    op.drop_index(op.f("ix_notification_delivery_status"), table_name="notification_delivery")
    op.drop_index(op.f("ix_notification_delivery_recipient_user_id"), table_name="notification_delivery")
    op.drop_index(op.f("ix_notification_delivery_recipient_role"), table_name="notification_delivery")
    op.drop_index(op.f("ix_notification_delivery_order_id"), table_name="notification_delivery")
    op.drop_index(op.f("ix_notification_delivery_event_type"), table_name="notification_delivery")
    op.drop_index(op.f("ix_notification_delivery_delivery_id"), table_name="notification_delivery")
    op.drop_index(op.f("ix_notification_delivery_channel"), table_name="notification_delivery")
    op.drop_table("notification_delivery")

    bind = op.get_bind()
    notificationdeliverystatus.drop(bind, checkfirst=True)
    notificationchannel.drop(bind, checkfirst=True)
