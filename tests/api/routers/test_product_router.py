from types import SimpleNamespace
from unittest.mock import AsyncMock

from core.db import get_db
from core.models import UserRole
from routers import product_router
from routers.user_router import get_current_user
from tests.conftest import create_test_client


async def _fake_db():
    yield object()


def test_get_product_by_id_returns_404_when_missing(monkeypatch):
    monkeypatch.setattr(product_router.product_service, "get_product_by_id", AsyncMock(return_value=None))
    client = create_test_client(product_router.router, dependency_overrides={get_db: _fake_db})

    response = client.get("/products/999")
    assert response.status_code == 404


def test_get_all_products_returns_list(monkeypatch):
    monkeypatch.setattr(product_router.product_service, "get_all_products", AsyncMock(return_value=[]))
    client = create_test_client(product_router.router, dependency_overrides={get_db: _fake_db})

    response = client.get("/products/")
    assert response.status_code == 200
    assert response.json() == []


def test_create_product_requires_auth(monkeypatch):
    monkeypatch.setattr(product_router.product_service, "create_product", AsyncMock())
    client = create_test_client(product_router.router, dependency_overrides={get_db: _fake_db})

    response = client.post(
        "/products/",
        json={
            "name": "Salmon",
            "description": "Fresh fish",
            "image_url": "https://example.com/salmon.jpg",
            "base_unit_price": "10.00",
            "unit": "kg",
            "available_quantity": "6.000",
            "is_active": True,
        },
    )
    assert response.status_code == 401


def test_create_product_with_auth_returns_201(monkeypatch):
    created = {
        "id": 1,
        "sku": "RIBA-20260416-TEST",
        "name": "Salmon",
        "description": "Fresh fish",
        "image_url": "https://example.com/salmon.jpg",
        "base_unit_price": "10.00",
        "last_purchase_price": None,
        "unit": "kg",
        "available_quantity": "6.000",
        "reserved_quantity": "0.000",
        "stock_on_hand": "6.000",
        "is_active": True,
        "created_at": "2026-04-16T12:00:00Z",
        "updated_at": "2026-04-16T12:00:00Z",
    }
    monkeypatch.setattr(product_router.product_service, "create_product", AsyncMock(return_value=created))
    client = create_test_client(
        product_router.router,
        dependency_overrides={get_db: _fake_db, get_current_user: lambda: {"id": 1}},
    )

    response = client.post(
        "/products/",
        json={
            "name": "Salmon",
            "description": "Fresh fish",
            "image_url": "https://example.com/salmon.jpg",
            "base_unit_price": "10.00",
            "unit": "kg",
            "available_quantity": "6.000",
            "is_active": True,
        },
    )
    assert response.status_code == 201


def test_admin_sales_analytics_requires_admin_and_returns_payload(monkeypatch):
    monkeypatch.setattr(
        product_router.analytics_service,
        "get_product_sales_analytics",
        AsyncMock(
            return_value=SimpleNamespace(
                period="month",
                sort_by="quantity",
                generated_at="2026-05-06T10:00:00Z",
                period_start="2026-04-06T00:00:00Z",
                period_end="2026-05-07T00:00:00Z",
                summary=SimpleNamespace(
                    total_products=2,
                    total_quantity="12.000",
                    total_revenue="2200.00",
                    total_orders=5,
                ),
                items=[
                    SimpleNamespace(
                        product_id=1,
                        product_name="Sea Bass",
                        product_sku="RIBA-0001",
                        unit="kg",
                        total_quantity="8.000",
                        total_revenue="1600.00",
                        order_count=3,
                    )
                ],
            )
        ),
    )
    client = create_test_client(
        product_router.router,
        dependency_overrides={get_db: _fake_db, get_current_user: lambda: SimpleNamespace(role=UserRole.ADMIN)},
    )

    response = client.get("/products/admin/sales-analytics")

    assert response.status_code == 200
    assert response.json()["summary"]["total_products"] == 2
    assert response.json()["items"][0]["product_name"] == "Sea Bass"
