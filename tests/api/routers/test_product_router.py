from unittest.mock import AsyncMock

from core.db import get_db
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
            "base_unit_price": "10.00",
            "unit": "kg",
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
        "base_unit_price": "10.00",
        "unit": "kg",
        "is_active": True,
        "created_at": "2026-04-16T12:00:00Z",
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
            "base_unit_price": "10.00",
            "unit": "kg",
            "is_active": True,
        },
    )
    assert response.status_code == 201
