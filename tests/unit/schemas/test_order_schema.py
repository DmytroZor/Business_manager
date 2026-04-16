from decimal import Decimal

import pytest
from pydantic import ValidationError

from manage.schemas.order_schema import OrderCreate, OrderItemCreate


def test_order_item_quantity_is_quantized_to_three_decimals():
    item = OrderItemCreate(product_id=1, quantity=Decimal("1.2349"))
    assert item.quantity == Decimal("1.234")


def test_order_create_requires_at_least_one_item():
    with pytest.raises(ValidationError):
        OrderCreate(delivery_address_id=1, items=[])
