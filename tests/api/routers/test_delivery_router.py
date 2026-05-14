from types import SimpleNamespace
from unittest.mock import AsyncMock

from core.db import get_db
from core.models import DeliveryStatus, OrderStatus, UserRole
from routers import delivery_router
from routers.user_router import get_current_user
from tests.conftest import create_test_client


async def _fake_db():
    yield object()


def test_get_available_orders_for_courier_returns_list(monkeypatch):
    mocked_orders = [
        {
            "id": 10,
            "customer_id": 5,
            "delivery_address_id": 3,
            "status": OrderStatus.PLACED,
            "placed_at": "2026-04-26T12:00:00Z",
            "total_amount": "100.00",
            "note": None,
            "items": [],
        }
    ]
    monkeypatch.setattr(
        delivery_router.delivery_service,
        "get_available_orders_for_courier",
        AsyncMock(return_value=mocked_orders),
    )
    client = create_test_client(
        delivery_router.router,
        dependency_overrides={
            get_db: _fake_db,
            get_current_user: lambda: SimpleNamespace(id=1, role=UserRole.COURIER),
        },
    )

    response = client.get("/deliveries/available-orders")

    assert response.status_code == 200
    assert response.json()[0]["id"] == 10


def test_self_assign_delivery_returns_201(monkeypatch):
    mocked_delivery = {
        "id": 7,
        "order_id": 10,
        "courier_id": 2,
        "status": DeliveryStatus.ASSIGNED,
        "scheduled_at": None,
        "assigned_at": "2026-04-26T12:10:00Z",
        "picked_up_at": None,
        "delivered_at": None,
        "failed_reason": None,
        "fee": "0.00",
        "created_at": "2026-04-26T12:10:00Z",
    }
    monkeypatch.setattr(
        delivery_router.delivery_service,
        "self_assign_delivery",
        AsyncMock(return_value=mocked_delivery),
    )
    client = create_test_client(
        delivery_router.router,
        dependency_overrides={
            get_db: _fake_db,
            get_current_user: lambda: SimpleNamespace(id=1, role=UserRole.COURIER),
        },
    )

    response = client.post("/deliveries/orders/10/self-assign", json={})

    assert response.status_code == 201
    assert response.json()["order_id"] == 10
