from decimal import Decimal

import pytest
from pydantic import ValidationError

from manage.schemas.order_schema import AdminPhoneOrderCreate, OrderCreate, OrderItemCreate


def test_order_item_quantity_is_quantized_to_three_decimals():
    item = OrderItemCreate(product_id=1, quantity=Decimal("1.2349"))
    assert item.quantity == Decimal("1.234")


def test_order_create_requires_at_least_one_item():
    with pytest.raises(ValidationError):
        OrderCreate(delivery_address_id=1, items=[])


def test_admin_phone_order_normalizes_phone_number():
    payload = AdminPhoneOrderCreate(
        customer_full_name="Test Customer",
        customer_phone_number="0671234567",
        street="Main Street",
        building="12A",
        items=[{"product_id": 1, "quantity": "1"}],
    )

    assert payload.customer_phone_number == "+380671234567"


def test_admin_phone_order_rejects_invalid_phone_number():
    with pytest.raises(ValidationError):
        AdminPhoneOrderCreate(
            customer_full_name="Test Customer",
            customer_phone_number="12345",
            street="Main Street",
            building="12A",
            items=[{"product_id": 1, "quantity": "1"}],
        )
