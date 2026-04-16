from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from core.models import Customer
from manage.services import order_service


class _Result:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


@pytest.mark.asyncio
async def test_get_customer_by_user_id_not_found():
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_Result(None))

    with pytest.raises(HTTPException) as exc:
        await order_service.get_customer_by_user_id(db, user_id=10)

    assert exc.value.status_code == 400
    assert "Customer profile not found" in exc.value.detail


@pytest.mark.asyncio
async def test_get_customer_by_user_id_returns_customer():
    db = AsyncMock()
    customer = Customer(user_id=10)
    db.execute = AsyncMock(return_value=_Result(customer))

    result = await order_service.get_customer_by_user_id(db, user_id=10)
    assert result is customer


def test_quantize_money_rounds_down_to_two_decimals():
    value = order_service._quantize_money(Decimal("10.239"))
    assert value == Decimal("10.23")
