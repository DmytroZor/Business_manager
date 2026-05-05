import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastapi.staticfiles import StaticFiles

from core.db import get_db
from core.models import OrderStatus, UserRole
from manage.admin import ADMIN_STATIC_DIR, router

admin_router_module = importlib.import_module("manage.admin.router")


async def _fake_db():
    yield object()


def _create_admin_test_client() -> TestClient:
    app = FastAPI()
    app.mount("/admin/static", StaticFiles(directory=ADMIN_STATIC_DIR), name="admin_static")
    app.include_router(router)
    app.dependency_overrides[get_db] = _fake_db
    return TestClient(app)


def test_admin_orders_dashboard_renders_selected_order(monkeypatch):
    monkeypatch.setattr(
        admin_router_module,
        "_require_admin_user",
        AsyncMock(return_value=SimpleNamespace(full_name="Admin", role=UserRole.ADMIN)),
    )
    monkeypatch.setattr(admin_router_module.order_service, "count_orders_for_admin", AsyncMock(return_value=1))
    monkeypatch.setattr(admin_router_module.order_service, "get_orders_for_admin", AsyncMock(return_value=[SimpleNamespace()]))
    monkeypatch.setattr(admin_router_module.order_service, "get_order_for_admin", AsyncMock(return_value=SimpleNamespace()))
    monkeypatch.setattr(admin_router_module, "_load_order_stats", AsyncMock(return_value={"placed": 1, "open": 1}))
    monkeypatch.setattr(admin_router_module, "_load_admin_couriers", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        admin_router_module.order_service,
        "build_admin_order_payload",
        lambda order: {
            "id": 11,
            "status": OrderStatus.PLACED,
            "placed_at": "2026-04-29T17:53:00Z",
            "total_amount": "1110.00",
            "note": "Call before delivery",
            "customer": {
                "user_id": 100,
                "customer_id": 200,
                "full_name": "Phone Customer",
                "phone": "+380671234567",
                "email": "customer@example.com",
            },
            "delivery_address": {
                "id": 300,
                "street": "Main Street",
                "building": "12A",
                "apartment": "7",
                "notes": "Blue door",
            },
            "items": [
                {
                    "id": 1,
                    "product_id": 10,
                    "product_name": "Salmon",
                    "product_sku": "RIBA-TEST",
                    "unit": "kg",
                    "unit_price": "370.00",
                    "quantity": "3.000",
                    "subtotal": "1110.00",
                }
            ],
            "active_delivery": None,
        },
    )

    client = _create_admin_test_client()
    response = client.get("/admin/orders?selected_order_id=11")

    assert response.status_code == 200
    assert "Order #11" in response.text
    assert "Salmon" in response.text
    assert "Placed on" in response.text


def test_admin_products_page_renders_selected_product(monkeypatch):
    monkeypatch.setattr(
        admin_router_module,
        "_require_admin_user",
        AsyncMock(return_value=SimpleNamespace(full_name="Admin", role=UserRole.ADMIN)),
    )
    monkeypatch.setattr(admin_router_module, "_load_product_stats", AsyncMock(return_value={"total": 1, "active": 1}))
    product = SimpleNamespace(
        id=5,
        sku="RIBA-TEST-05",
        name="Mackerel",
        description="Fresh fish",
        image_url="https://example.com/mackerel.jpg",
        base_unit_price="210.00",
        last_purchase_price="170.00",
        unit="kg",
        available_quantity="12.000",
        reserved_quantity="2.000",
        stock_on_hand="14.000",
        is_active=True,
        created_at="2026-04-29T10:00:00Z",
        updated_at="2026-04-29T11:00:00Z",
    )
    monkeypatch.setattr(admin_router_module.product_service, "get_all_products", AsyncMock(return_value=[product]))
    monkeypatch.setattr(admin_router_module.product_service, "get_product_by_id", AsyncMock(return_value=product))
    monkeypatch.setattr(admin_router_module.product_service, "get_product_batches", AsyncMock(return_value=[]))
    monkeypatch.setattr(admin_router_module.product_service, "list_recent_stock_documents", AsyncMock(return_value=[]))

    client = _create_admin_test_client()
    response = client.get("/admin/products?selected_product_id=5")

    assert response.status_code == 200
    assert "Products, batches, and stock documents" in response.text
    assert "Mackerel" in response.text
    assert "Warehouse document" in response.text


def test_admin_orders_dashboard_renders_pagination(monkeypatch):
    monkeypatch.setattr(
        admin_router_module,
        "_require_admin_user",
        AsyncMock(return_value=SimpleNamespace(full_name="Admin", role=UserRole.ADMIN)),
    )
    monkeypatch.setattr(admin_router_module.order_service, "count_orders_for_admin", AsyncMock(return_value=23))
    monkeypatch.setattr(admin_router_module.order_service, "get_orders_for_admin", AsyncMock(return_value=[SimpleNamespace()]))
    monkeypatch.setattr(admin_router_module, "_load_order_stats", AsyncMock(return_value={"placed": 7, "open": 7}))
    monkeypatch.setattr(admin_router_module, "_load_admin_couriers", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        admin_router_module.order_service,
        "build_admin_order_payload",
        lambda order: {
            "id": 15,
            "status": OrderStatus.PLACED,
            "placed_at": "2026-04-29T17:53:00Z",
            "total_amount": "220.00",
            "note": None,
            "customer": {
                "user_id": 100,
                "customer_id": 200,
                "full_name": "Queue Customer",
                "phone": "+380671234567",
                "email": None,
            },
            "delivery_address": {
                "id": 300,
                "street": "Queue Street",
                "building": "12A",
                "apartment": None,
                "notes": None,
            },
            "items": [],
            "active_delivery": None,
            "events": [],
        },
    )

    client = _create_admin_test_client()
    response = client.get("/admin/orders?page=2")

    assert response.status_code == 200
    assert "Queue page 2 of 3." in response.text
    assert "Queue Customer" in response.text


def test_admin_orders_dashboard_passes_date_filter(monkeypatch):
    monkeypatch.setattr(
        admin_router_module,
        "_require_admin_user",
        AsyncMock(return_value=SimpleNamespace(full_name="Admin", role=UserRole.ADMIN)),
    )
    count_mock = AsyncMock(return_value=0)
    list_mock = AsyncMock(return_value=[])
    monkeypatch.setattr(admin_router_module.order_service, "count_orders_for_admin", count_mock)
    monkeypatch.setattr(admin_router_module.order_service, "get_orders_for_admin", list_mock)
    monkeypatch.setattr(admin_router_module, "_load_order_stats", AsyncMock(return_value={"placed": 0, "open": 0}))
    monkeypatch.setattr(admin_router_module, "_load_admin_couriers", AsyncMock(return_value=[]))

    client = _create_admin_test_client()
    response = client.get("/admin/orders?date_filter=today")

    assert response.status_code == 200
    assert "Placed on" in response.text
    count_mock.assert_awaited_once()
    list_mock.assert_awaited_once()
    assert count_mock.await_args.kwargs["date_filter"] == "today"
    assert list_mock.await_args.kwargs["date_filter"] == "today"


def test_admin_couriers_page_renders_create_form(monkeypatch):
    monkeypatch.setattr(
        admin_router_module,
        "_require_admin_user",
        AsyncMock(return_value=SimpleNamespace(full_name="Admin", role=UserRole.ADMIN)),
    )
    monkeypatch.setattr(admin_router_module, "_load_admin_couriers", AsyncMock(return_value=[]))

    client = _create_admin_test_client()
    response = client.get("/admin/couriers")

    assert response.status_code == 200
    assert "Create courier account" in response.text
    assert "Create courier" in response.text
