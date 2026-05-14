import importlib
from datetime import date
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


def test_admin_language_switch_sets_cookie():
    client = _create_admin_test_client()

    response = client.get("/admin/ui-language/uk?next=/admin/orders", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/admin/orders"
    assert "bms_admin_lang=uk" in response.headers["set-cookie"]


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
    assert "Оформлено" in response.text
    assert "built-in method items" not in response.text


def test_admin_phone_order_page_renders_without_dict_items_artifact(monkeypatch):
    monkeypatch.setattr(
        admin_router_module,
        "_require_admin_user",
        AsyncMock(return_value=SimpleNamespace(full_name="Admin", role=UserRole.ADMIN)),
    )
    monkeypatch.setattr(
        admin_router_module.product_service,
        "get_all_products",
        AsyncMock(
            return_value=[
                SimpleNamespace(
                    id=1,
                    name="Sea Bass",
                    base_unit_price="450.00",
                    unit="kg",
                )
            ]
        ),
    )

    client = _create_admin_test_client()
    response = client.get("/admin/phone-orders/new")

    assert response.status_code == 200
    assert "built-in method items" not in response.text


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
        last_purchase_at="2026-04-28",
        unit="kg",
        available_quantity="12.000",
        reserved_quantity="2.000",
        stock_on_hand="14.000",
        is_active=True,
        created_at="2026-04-29T10:00:00Z",
        updated_at="2026-04-29T11:00:00Z",
    )
    monkeypatch.setattr(admin_router_module.product_service, "get_all_products", AsyncMock(return_value=[product]))
    monkeypatch.setattr(admin_router_module.product_service, "count_products", AsyncMock(return_value=1))
    monkeypatch.setattr(admin_router_module.product_service, "get_product_by_id", AsyncMock(return_value=product))
    monkeypatch.setattr(admin_router_module.product_service, "get_product_batches", AsyncMock(return_value=[]))

    client = _create_admin_test_client()
    response = client.get("/admin/products?selected_product_id=5")

    assert response.status_code == 200
    assert "\u0422\u043e\u0432\u0430\u0440\u0438 \u0442\u0430 \u0437\u0430\u043b\u0438\u0448\u043a\u0438" in response.text
    assert "Mackerel" in response.text
    assert "\u0428\u0432\u0438\u0434\u043a\u0435 \u043a\u043e\u0440\u0438\u0433\u0443\u0432\u0430\u043d\u043d\u044f \u0437\u0430\u043b\u0438\u0448\u043a\u0443" in response.text


def test_admin_products_page_renders_pagination_and_passes_category_filter(monkeypatch):
    monkeypatch.setattr(
        admin_router_module,
        "_require_admin_user",
        AsyncMock(return_value=SimpleNamespace(full_name="Admin", role=UserRole.ADMIN)),
    )
    monkeypatch.setattr(admin_router_module, "_load_product_stats", AsyncMock(return_value={"total": 27, "active": 27}))
    count_mock = AsyncMock(return_value=27)
    list_mock = AsyncMock(
        return_value=[
            SimpleNamespace(
                id=9,
                sku="SEA-0009",
                name="Shrimp",
                description="Seafood",
                image_url=None,
                base_unit_price="350.00",
                last_purchase_price=None,
                last_purchase_at=None,
                unit="kg",
                available_quantity="5.000",
                reserved_quantity="0.000",
                stock_on_hand="5.000",
                is_active=True,
                created_at="2026-04-29T10:00:00Z",
                updated_at="2026-04-29T11:00:00Z",
            )
        ]
    )
    monkeypatch.setattr(admin_router_module.product_service, "count_products", count_mock)
    monkeypatch.setattr(admin_router_module.product_service, "get_all_products", list_mock)
    monkeypatch.setattr(admin_router_module.product_service, "get_product_by_id", AsyncMock(return_value=None))
    monkeypatch.setattr(admin_router_module.product_service, "get_product_batches", AsyncMock(return_value=[]))

    client = _create_admin_test_client()
    response = client.get("/admin/products?category_filter=seafood&page=2")

    assert response.status_code == 200
    assert "\u0421\u0442\u043e\u0440\u0456\u043d\u043a\u0430 2 / 3" in response.text
    assert "\u041f\u0435\u0440\u0435\u0439\u0442\u0438" in response.text
    assert 'class="page-link is-active"' in response.text
    assert 'name="page"' in response.text
    count_mock.assert_awaited_once()
    list_mock.assert_awaited_once()
    assert count_mock.await_args.kwargs["category_filter"] == "seafood"
    assert list_mock.await_args.kwargs["category_filter"] == "seafood"
    assert list_mock.await_args.kwargs["offset"] == 10
    assert list_mock.await_args.kwargs["limit"] == 10


def _fake_stock_document():
    return SimpleNamespace(
        id=1,
        document_number="REC-2026-05-10-01",
        document_type=SimpleNamespace(value="receipt"),
        document_date=date(2026, 5, 10),
        supplier=SimpleNamespace(name="Seafood Supplier"),
        created_by_user=SimpleNamespace(full_name="Admin"),
        note="Morning receipt",
        created_at="2026-05-10T09:00:00Z",
        items=[
            SimpleNamespace(
                id=11,
                product_name="Sea bass",
                unit="kg",
                quantity_value="5.000",
                applied_delta="5.000",
                sale_unit_price="450.00",
                purchase_unit_price="320.00",
                batch_code="BATCH-01",
                serial_code=None,
                expires_at=date(2026, 5, 20),
                note=None,
            )
        ],
    )


def test_admin_stock_documents_page_renders_list(monkeypatch):
    monkeypatch.setattr(
        admin_router_module,
        "_require_admin_user",
        AsyncMock(return_value=SimpleNamespace(full_name="Admin", role=UserRole.ADMIN)),
    )
    monkeypatch.setattr(
        admin_router_module.product_service,
        "list_recent_stock_documents",
        AsyncMock(return_value=[_fake_stock_document()]),
    )

    client = _create_admin_test_client()
    response = client.get("/admin/stock-documents")

    assert response.status_code == 200
    assert "Накладні" in response.text
    assert "REC-2026-05-10-01" in response.text
    assert "Sea bass" in response.text


def test_admin_stock_documents_page_defaults_to_today_period(monkeypatch):
    monkeypatch.setattr(
        admin_router_module,
        "_require_admin_user",
        AsyncMock(return_value=SimpleNamespace(full_name="Admin", role=UserRole.ADMIN)),
    )
    list_mock = AsyncMock(return_value=[_fake_stock_document()])
    monkeypatch.setattr(admin_router_module.product_service, "list_recent_stock_documents", list_mock)

    client = _create_admin_test_client()
    response = client.get("/admin/stock-documents")

    assert response.status_code == 200
    list_mock.assert_awaited_once()
    assert list_mock.await_args.kwargs["days_back"] == 1


def test_admin_stock_document_create_page_renders_form(monkeypatch):
    monkeypatch.setattr(
        admin_router_module,
        "_require_admin_user",
        AsyncMock(return_value=SimpleNamespace(full_name="Admin", role=UserRole.ADMIN)),
    )
    monkeypatch.setattr(admin_router_module, "_load_product_reference_options", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        admin_router_module.product_service,
        "get_next_receipt_document_number",
        AsyncMock(return_value="REC-2026-05-10-01"),
    )

    client = _create_admin_test_client()
    response = client.get("/admin/stock-documents/new")

    assert response.status_code == 200
    assert "Створення накладної" in response.text
    assert "REC-2026-05-10-01" in response.text


def test_admin_stock_document_export_returns_xlsx(monkeypatch):
    monkeypatch.setattr(
        admin_router_module,
        "_require_admin_user",
        AsyncMock(return_value=SimpleNamespace(full_name="Admin", role=UserRole.ADMIN)),
    )
    monkeypatch.setattr(
        admin_router_module.product_service,
        "get_stock_document_by_id",
        AsyncMock(return_value=_fake_stock_document()),
    )

    client = _create_admin_test_client()
    response = client.get("/admin/stock-documents/1/export.xlsx")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert "REC-2026-05-10-01.xlsx" in response.headers["content-disposition"]


def test_admin_product_delete_requires_reason(monkeypatch):
    monkeypatch.setattr(
        admin_router_module,
        "_require_admin_user",
        AsyncMock(return_value=SimpleNamespace(id=7, full_name="Admin", role=UserRole.ADMIN)),
    )
    monkeypatch.setattr(admin_router_module, "_load_product_stats", AsyncMock(return_value={"total": 1, "active": 1}))
    product = SimpleNamespace(
        id=5,
        sku="RIBA-TEST-05",
        name="Hake",
        description="Fresh fish",
        image_url=None,
        base_unit_price="210.00",
        last_purchase_price=None,
        last_purchase_at=None,
        unit="kg",
        available_quantity="0.000",
        reserved_quantity="0.000",
        stock_on_hand="0.000",
        is_active=True,
        created_at="2026-04-29T10:00:00Z",
        updated_at="2026-04-29T11:00:00Z",
    )
    monkeypatch.setattr(admin_router_module.product_service, "get_all_products", AsyncMock(return_value=[product]))
    monkeypatch.setattr(admin_router_module.product_service, "count_products", AsyncMock(return_value=1))
    monkeypatch.setattr(admin_router_module.product_service, "get_product_by_id", AsyncMock(return_value=product))
    monkeypatch.setattr(admin_router_module.product_service, "get_product_batches", AsyncMock(return_value=[]))

    client = _create_admin_test_client()
    response = client.post("/admin/products/5/delete", data={"page": "1"})

    assert response.status_code == 400
    assert "Вкажіть причину видалення товару" in response.text


def test_admin_sales_analytics_page_renders_summary(monkeypatch):
    monkeypatch.setattr(
        admin_router_module,
        "_require_admin_user",
        AsyncMock(return_value=SimpleNamespace(full_name="Admin", role=UserRole.ADMIN)),
    )
    monkeypatch.setattr(
        admin_router_module.analytics_service,
        "get_product_sales_analytics",
        AsyncMock(
            return_value=SimpleNamespace(
                period="month",
                sort_by="quantity",
                generated_at="2026-05-06T10:00:00Z",
                period_start="2026-04-06T00:00:00Z",
                period_end="2026-05-07T00:00:00Z",
                summary=SimpleNamespace(
                    total_products=3,
                    total_quantity="25.000",
                    total_revenue="4200.00",
                    total_orders=7,
                ),
                items=[
                    SimpleNamespace(
                        product_id=1,
                        product_name="Sea Bass",
                        product_sku="RIBA-0001",
                        unit="kg",
                        total_quantity="10.000",
                        total_revenue="1800.00",
                        order_count=4,
                    )
                ],
            )
        ),
    )

    client = _create_admin_test_client()
    response = client.get("/admin/analytics/products")

    assert response.status_code == 200
    assert "Аналітика товарних продажів" in response.text
    assert "Sea Bass" in response.text


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
    assert "Сторінка черги 2 з 3." in response.text
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
    assert "Оформлено" in response.text
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
    assert "Створення акаунта кур’єра" in response.text
    assert "Створити кур’єра" in response.text
