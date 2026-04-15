"""harden constraints and courier user id

Revision ID: b7f2c1d9e4a1
Revises: 33a361e4f76e
Create Date: 2026-04-15 12:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b7f2c1d9e4a1"
down_revision: Union[str, Sequence[str], None] = "33a361e4f76e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # courier.users_id -> courier.user_id
    op.alter_column("courier", "users_id", new_column_name="user_id")

    # "order" table name is a reserved SQL keyword; use "orders"
    op.rename_table("order", "orders")

    # address building/apartment: Integer -> String to support values like 10/A
    op.alter_column(
        "address",
        "building",
        existing_type=sa.Integer(),
        type_=sa.String(length=20),
        postgresql_using="building::varchar",
        existing_nullable=False,
    )
    op.alter_column(
        "address",
        "apartment",
        existing_type=sa.Integer(),
        type_=sa.String(length=20),
        postgresql_using="apartment::varchar",
        existing_nullable=True,
    )

    # order_item.quantity: Float -> Numeric(10,3)
    op.alter_column(
        "order_item",
        "quantity",
        existing_type=sa.Float(),
        type_=sa.Numeric(10, 3),
        postgresql_using="quantity::numeric",
        existing_nullable=False,
    )

    # new unique constraint for duplicate customer addresses
    op.create_unique_constraint(
        "uq_address_customer_location",
        "address",
        ["customer_id", "street", "building", "apartment"],
    )

    # checks for domain rules
    op.create_check_constraint(
        "ck_product_base_unit_price_positive",
        "product",
        "base_unit_price > 0",
    )
    op.create_check_constraint(
        "ck_order_item_unit_price_positive",
        "order_item",
        "unit_price > 0",
    )
    op.create_check_constraint(
        "ck_order_item_quantity_positive",
        "order_item",
        "quantity > 0",
    )
    op.create_check_constraint(
        "ck_order_item_subtotal_non_negative",
        "order_item",
        "subtotal >= 0",
    )
    op.create_check_constraint(
        "ck_payment_amount_positive",
        "payment",
        "amount > 0",
    )
    op.create_unique_constraint(
        "uq_payment_transaction_id",
        "payment",
        ["transaction_id"],
    )
    op.create_check_constraint(
        "ck_delivery_fee_non_negative",
        "delivery",
        "fee >= 0",
    )
    op.create_check_constraint(
        "ck_review_rating_between_1_5",
        "review",
        "rating >= 1 AND rating <= 5",
    )

    # compound index for courier task filtering
    op.create_index(
        "ix_delivery_courier_status",
        "delivery",
        ["courier_id", "status"],
        unique=False,
    )

    # timezone-aware timestamps (UTC)
    op.alter_column(
        "users",
        "created_at",
        existing_type=sa.DateTime(),
        type_=sa.DateTime(timezone=True),
        postgresql_using="created_at AT TIME ZONE 'UTC'",
        existing_nullable=False,
        server_default=sa.text("now()"),
    )
    op.alter_column(
        "address",
        "created_at",
        existing_type=sa.DateTime(),
        type_=sa.DateTime(timezone=True),
        postgresql_using="created_at AT TIME ZONE 'UTC'",
        existing_nullable=False,
        server_default=sa.text("now()"),
    )
    op.alter_column(
        "product",
        "created_at",
        existing_type=sa.DateTime(),
        type_=sa.DateTime(timezone=True),
        postgresql_using="created_at AT TIME ZONE 'UTC'",
        existing_nullable=False,
        server_default=sa.text("now()"),
    )
    op.alter_column(
        "product",
        "updated_at",
        existing_type=sa.DateTime(),
        type_=sa.DateTime(timezone=True),
        postgresql_using="updated_at AT TIME ZONE 'UTC'",
        existing_nullable=False,
        server_default=sa.text("now()"),
    )
    op.alter_column(
        "orders",
        "placed_at",
        existing_type=sa.DateTime(),
        type_=sa.DateTime(timezone=True),
        postgresql_using="placed_at AT TIME ZONE 'UTC'",
        existing_nullable=False,
        server_default=sa.text("now()"),
    )
    op.alter_column(
        "payment",
        "created_at",
        existing_type=sa.DateTime(),
        type_=sa.DateTime(timezone=True),
        postgresql_using="created_at AT TIME ZONE 'UTC'",
        existing_nullable=False,
        server_default=sa.text("now()"),
    )
    op.alter_column(
        "delivery",
        "scheduled_at",
        existing_type=sa.DateTime(),
        type_=sa.DateTime(timezone=True),
        postgresql_using="scheduled_at AT TIME ZONE 'UTC'",
        existing_nullable=True,
    )
    op.alter_column(
        "delivery",
        "assigned_at",
        existing_type=sa.DateTime(),
        type_=sa.DateTime(timezone=True),
        postgresql_using="assigned_at AT TIME ZONE 'UTC'",
        existing_nullable=True,
    )
    op.alter_column(
        "delivery",
        "picked_up_at",
        existing_type=sa.DateTime(),
        type_=sa.DateTime(timezone=True),
        postgresql_using="picked_up_at AT TIME ZONE 'UTC'",
        existing_nullable=True,
    )
    op.alter_column(
        "delivery",
        "delivered_at",
        existing_type=sa.DateTime(),
        type_=sa.DateTime(timezone=True),
        postgresql_using="delivered_at AT TIME ZONE 'UTC'",
        existing_nullable=True,
    )
    op.alter_column(
        "delivery",
        "created_at",
        existing_type=sa.DateTime(),
        type_=sa.DateTime(timezone=True),
        postgresql_using="created_at AT TIME ZONE 'UTC'",
        existing_nullable=False,
        server_default=sa.text("now()"),
    )
    op.alter_column(
        "review",
        "created_at",
        existing_type=sa.DateTime(),
        type_=sa.DateTime(timezone=True),
        postgresql_using="created_at AT TIME ZONE 'UTC'",
        existing_nullable=False,
        server_default=sa.text("now()"),
    )


def downgrade() -> None:
    op.alter_column(
        "review",
        "created_at",
        existing_type=sa.DateTime(timezone=True),
        type_=sa.DateTime(),
        postgresql_using="created_at AT TIME ZONE 'UTC'",
        existing_nullable=False,
        server_default=None,
    )
    op.alter_column(
        "delivery",
        "created_at",
        existing_type=sa.DateTime(timezone=True),
        type_=sa.DateTime(),
        postgresql_using="created_at AT TIME ZONE 'UTC'",
        existing_nullable=False,
        server_default=None,
    )
    op.alter_column(
        "delivery",
        "delivered_at",
        existing_type=sa.DateTime(timezone=True),
        type_=sa.DateTime(),
        postgresql_using="delivered_at AT TIME ZONE 'UTC'",
        existing_nullable=True,
    )
    op.alter_column(
        "delivery",
        "picked_up_at",
        existing_type=sa.DateTime(timezone=True),
        type_=sa.DateTime(),
        postgresql_using="picked_up_at AT TIME ZONE 'UTC'",
        existing_nullable=True,
    )
    op.alter_column(
        "delivery",
        "assigned_at",
        existing_type=sa.DateTime(timezone=True),
        type_=sa.DateTime(),
        postgresql_using="assigned_at AT TIME ZONE 'UTC'",
        existing_nullable=True,
    )
    op.alter_column(
        "delivery",
        "scheduled_at",
        existing_type=sa.DateTime(timezone=True),
        type_=sa.DateTime(),
        postgresql_using="scheduled_at AT TIME ZONE 'UTC'",
        existing_nullable=True,
    )
    op.alter_column(
        "payment",
        "created_at",
        existing_type=sa.DateTime(timezone=True),
        type_=sa.DateTime(),
        postgresql_using="created_at AT TIME ZONE 'UTC'",
        existing_nullable=False,
        server_default=None,
    )
    op.alter_column(
        "orders",
        "placed_at",
        existing_type=sa.DateTime(timezone=True),
        type_=sa.DateTime(),
        postgresql_using="placed_at AT TIME ZONE 'UTC'",
        existing_nullable=False,
        server_default=None,
    )
    op.alter_column(
        "product",
        "updated_at",
        existing_type=sa.DateTime(timezone=True),
        type_=sa.DateTime(),
        postgresql_using="updated_at AT TIME ZONE 'UTC'",
        existing_nullable=False,
        server_default=None,
    )
    op.alter_column(
        "product",
        "created_at",
        existing_type=sa.DateTime(timezone=True),
        type_=sa.DateTime(),
        postgresql_using="created_at AT TIME ZONE 'UTC'",
        existing_nullable=False,
        server_default=None,
    )
    op.alter_column(
        "address",
        "created_at",
        existing_type=sa.DateTime(timezone=True),
        type_=sa.DateTime(),
        postgresql_using="created_at AT TIME ZONE 'UTC'",
        existing_nullable=False,
        server_default=None,
    )
    op.alter_column(
        "users",
        "created_at",
        existing_type=sa.DateTime(timezone=True),
        type_=sa.DateTime(),
        postgresql_using="created_at AT TIME ZONE 'UTC'",
        existing_nullable=False,
        server_default=None,
    )

    op.drop_index("ix_delivery_courier_status", table_name="delivery")

    op.drop_constraint("ck_review_rating_between_1_5", "review", type_="check")
    op.drop_constraint("ck_delivery_fee_non_negative", "delivery", type_="check")
    op.drop_constraint("uq_payment_transaction_id", "payment", type_="unique")
    op.drop_constraint("ck_payment_amount_positive", "payment", type_="check")
    op.drop_constraint("ck_order_item_subtotal_non_negative", "order_item", type_="check")
    op.drop_constraint("ck_order_item_quantity_positive", "order_item", type_="check")
    op.drop_constraint("ck_order_item_unit_price_positive", "order_item", type_="check")
    op.drop_constraint("ck_product_base_unit_price_positive", "product", type_="check")
    op.drop_constraint("uq_address_customer_location", "address", type_="unique")

    op.alter_column(
        "order_item",
        "quantity",
        existing_type=sa.Numeric(10, 3),
        type_=sa.Float(),
        postgresql_using="quantity::double precision",
        existing_nullable=False,
    )

    op.alter_column(
        "address",
        "apartment",
        existing_type=sa.String(length=20),
        type_=sa.Integer(),
        postgresql_using="NULLIF(apartment, '')::integer",
        existing_nullable=True,
    )
    op.alter_column(
        "address",
        "building",
        existing_type=sa.String(length=20),
        type_=sa.Integer(),
        postgresql_using="building::integer",
        existing_nullable=False,
    )

    op.rename_table("orders", "order")

    op.alter_column("courier", "user_id", new_column_name="users_id")
