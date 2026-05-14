"""add order event log

Revision ID: 89323c8591e7
Revises: f9b3c7a8d2e1
Create Date: 2026-05-03 21:47:10.893137

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '89323c8591e7'
down_revision: Union[str, Sequence[str], None] = 'f9b3c7a8d2e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


userrole = postgresql.ENUM(
    "CUSTOMER",
    "COURIER",
    "ADMIN",
    name="userrole",
    create_type=False,
)

orderstatus = postgresql.ENUM(
    "DRAFT",
    "PLACED",
    "PAID",
    "PREPARING",
    "OUT_FOR_DELIVERY",
    "DELIVERED",
    "CANCELLED",
    name="orderstatus",
    create_type=False,
)

deliverystatus = postgresql.ENUM(
    "PENDING",
    "ASSIGNED",
    "PICKED_UP",
    "DELIVERED",
    "FAILED",
    name="deliverystatus",
    create_type=False,
)


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('order_event_log',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('order_id', sa.Integer(), nullable=False),
    sa.Column('delivery_id', sa.Integer(), nullable=True),
    sa.Column('actor_user_id', sa.Integer(), nullable=True),
    sa.Column('actor_role', userrole, nullable=True),
    sa.Column('source', sa.String(length=100), nullable=False),
    sa.Column('event_type', sa.String(length=100), nullable=False),
    sa.Column('previous_order_status', orderstatus, nullable=True),
    sa.Column('new_order_status', orderstatus, nullable=True),
    sa.Column('previous_delivery_status', deliverystatus, nullable=True),
    sa.Column('new_delivery_status', deliverystatus, nullable=True),
    sa.Column('message', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['actor_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['delivery_id'], ['delivery.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['order_id'], ['orders.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_order_event_log_actor_user_id'), 'order_event_log', ['actor_user_id'], unique=False)
    op.create_index(op.f('ix_order_event_log_delivery_id'), 'order_event_log', ['delivery_id'], unique=False)
    op.create_index(op.f('ix_order_event_log_event_type'), 'order_event_log', ['event_type'], unique=False)
    op.create_index(op.f('ix_order_event_log_order_id'), 'order_event_log', ['order_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_order_event_log_order_id'), table_name='order_event_log')
    op.drop_index(op.f('ix_order_event_log_event_type'), table_name='order_event_log')
    op.drop_index(op.f('ix_order_event_log_delivery_id'), table_name='order_event_log')
    op.drop_index(op.f('ix_order_event_log_actor_user_id'), table_name='order_event_log')
    op.drop_table('order_event_log')
