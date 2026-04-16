from unittest.mock import AsyncMock
from types import SimpleNamespace

from core.db import get_db
from core.models import OrderStatus
from manage.schemas.order_schema import OrderOut, OrderItemOut
from routers import order_router
from routers.user_router import get_current_user
from tests.conftest import create_test_client


async def _fake_db():
    yield object()


def test_get_my_orders_returns_empty_list(monkeypatch):
    monkeypatch.setattr(order_router.order_service, "get_customer_orders", AsyncMock(return_value=[]))
    client = create_test_client(
        order_router.router,
        dependency_overrides={get_db: _fake_db, get_current_user: lambda: SimpleNamespace(id=1)},
    )

    response = client.get("/orders/")
    assert response.status_code == 200
    assert response.json() == []


def test_create_order_returns_201(monkeypatch):
    mocked_order = OrderOut(
        id=1,
        customer_id=1,
        delivery_address_id=2,
        status=OrderStatus.PLACED,
        placed_at="2026-04-16T12:00:00Z",
        total_amount="25.00",
        note="Leave at the door",
        items=[
            OrderItemOut(
                id=1,
                product_id=10,
                product_name="Salmon",
                product_sku="RIBA-TEST",
                unit="kg",
                unit_price="25.00",
                quantity="1.000",
                subtotal="25.00",
            )
        ],
    )

    monkeypatch.setattr(order_router.order_service, "create_order", AsyncMock(return_value=mocked_order))
    client = create_test_client(
        order_router.router,
        dependency_overrides={get_db: _fake_db, get_current_user: lambda: SimpleNamespace(id=1)},
    )

    response = client.post(
        "/orders/",
        json={
            "delivery_address_id": 2,
            "note": "Leave at the door",
            "items": [{"product_id": 10, "quantity": "1.000"}],
        },
    )

    assert response.status_code == 201
    assert response.json()["id"] == 1
