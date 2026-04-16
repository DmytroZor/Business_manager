from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from core.models import Product
from manage.schemas.product_schema import ProductUpdate
from manage.services import product_service


@pytest.mark.asyncio
async def test_product_update_trims_name(monkeypatch):
    db = AsyncMock()
    product = Product(
        name="Old name",
        sku="TEST-1",
        description="Old",
        base_unit_price=Decimal("10.00"),
        unit="kg",
        is_active=True,
    )
    monkeypatch.setattr(product_service, "get_product_by_id", AsyncMock(return_value=product))

    updated = await product_service.product_update_by_id(
        db=db,
        product_id=1,
        product_data=ProductUpdate(name="  New name  "),
    )

    assert updated.name == "New name"
    db.commit.assert_awaited_once()
    db.refresh.assert_awaited_once_with(product)


@pytest.mark.asyncio
async def test_product_update_rejects_empty_unit(monkeypatch):
    db = AsyncMock()
    product = Product(
        name="Test",
        sku="TEST-2",
        description=None,
        base_unit_price=Decimal("10.00"),
        unit="kg",
        is_active=True,
    )
    monkeypatch.setattr(product_service, "get_product_by_id", AsyncMock(return_value=product))

    with pytest.raises(HTTPException) as exc:
        await product_service.product_update_by_id(
            db=db,
            product_id=1,
            product_data=ProductUpdate(unit=" "),
        )

    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_product_update_returns_none_for_unknown_product(monkeypatch):
    db = AsyncMock()
    monkeypatch.setattr(product_service, "get_product_by_id", AsyncMock(return_value=None))

    result = await product_service.product_update_by_id(
        db=db,
        product_id=1,
        product_data=ProductUpdate(name="Name"),
    )

    assert result is None
