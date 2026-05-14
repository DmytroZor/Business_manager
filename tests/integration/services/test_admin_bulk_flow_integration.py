from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select

from core.models import Courier, DeliveryStatus, Order, OrderStatus, Product, StockDocument, User, UserRole
from manage.schemas.delivery_schema import DeliverySelfAssignCreate, DeliveryStatusUpdate
from manage.schemas.order_schema import AdminPhoneOrderCreate, OrderItemCreate
from manage.schemas.product_schema import ProductStockDocumentApply
from manage.services import delivery_service, order_service, product_service


def _build_receipt_payload(
    *,
    document_number: str,
    document_date: date,
    start_index: int,
    end_index: int,
) -> ProductStockDocumentApply:
    items = []
    for index in range(start_index, end_index + 1):
        items.append(
            {
                "name": f"Sea Product {index:02d}",
                "unit": "kg",
                "sale_unit_price": str(Decimal("200.00") + Decimal(index)),
                "purchase_unit_price": str(Decimal("150.00") + Decimal(index)),
                "quantity_value": str(Decimal("10.000") + (Decimal(index) / Decimal("10"))),
                "batch_code": f"BATCH-{index:03d}",
                "expires_at": "2026-12-31",
            }
        )
    return ProductStockDocumentApply.model_validate(
        {
            "document_type": "receipt",
            "document_number": document_number,
            "document_date": document_date,
            "supplier_name": "Bulk Seafood Supply",
            "supplier_phone": "+380501234567",
            "supplier_email": "supply@example.com",
            "note": f"Receipt for products {start_index}-{end_index}",
            "items": items,
        }
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_bulk_admin_flow_covers_products_receipts_phone_orders_and_courier(db_session, monkeypatch):
    monkeypatch.setattr(order_service.notification_service, "try_enqueue_new_order_notifications", AsyncMock())
    monkeypatch.setattr(delivery_service.notification_service, "try_enqueue_delivery_assigned_notification", AsyncMock())
    monkeypatch.setattr(delivery_service.notification_service, "try_enqueue_order_status_notifications", AsyncMock())

    await product_service.apply_stock_document(
        db_session,
        _build_receipt_payload(
            document_number="REC-2026-05-11-01",
            document_date=date(2026, 5, 11),
            start_index=1,
            end_index=40,
        ),
    )
    await product_service.apply_stock_document(
        db_session,
        _build_receipt_payload(
            document_number="REC-2026-05-11-02",
            document_date=date(2026, 5, 11),
            start_index=41,
            end_index=70,
        ),
    )

    products = (
        await db_session.execute(
            select(Product).order_by(Product.id.asc())
        )
    ).scalars().all()
    assert len(products) == 70
    assert await db_session.scalar(select(func.count(StockDocument.id))) == 2

    products_by_name = {product.name: product for product in products}

    for order_index in range(1, 26):
        primary_product = products_by_name[f"Sea Product {order_index:02d}"]
        secondary_product = products_by_name[f"Sea Product {order_index + 25:02d}"]
        payload = AdminPhoneOrderCreate(
            customer_full_name=f"Phone Customer {order_index:02d}",
            customer_phone_number=f"+38067000{order_index:04d}",
            customer_email=None,
            street=f"Warehouse Street {order_index}",
            building=str(order_index),
            apartment=str(order_index % 5 + 1),
            address_notes="Call before delivery",
            note="Created in integration test",
            items=[
                OrderItemCreate(product_id=primary_product.id, quantity=Decimal("0.500")),
                OrderItemCreate(product_id=secondary_product.id, quantity=Decimal("0.250")),
            ],
        )
        await order_service.create_phone_order_by_admin(db_session, payload)

    assert await db_session.scalar(select(func.count(Order.id))) == 25

    product_one_before_update = products_by_name["Sea Product 01"]
    product_two_before_update = products_by_name["Sea Product 02"]
    product_sixty_before_update = products_by_name["Sea Product 60"]

    update_payload = ProductStockDocumentApply.model_validate(
        {
            "document_type": "receipt",
            "document_number": "REC-2026-05-12-01",
            "document_date": date(2026, 5, 12),
            "supplier_name": "Bulk Seafood Supply",
            "items": [
                {
                    "product_id": product_one_before_update.id,
                    "name": product_one_before_update.name,
                    "unit": product_one_before_update.unit,
                    "sale_unit_price": "245.00",
                    "purchase_unit_price": "181.00",
                    "quantity_value": "3.000",
                    "batch_code": "RESTOCK-001",
                },
                    {
                        "product_id": product_two_before_update.id,
                        "name": product_two_before_update.name,
                        "unit": product_two_before_update.unit,
                        "sale_unit_price": "246.00",
                        "purchase_unit_price": "182.00",
                        "quantity_value": "-1.000",
                    },
                {
                    "product_id": product_sixty_before_update.id,
                    "name": product_sixty_before_update.name,
                    "unit": product_sixty_before_update.unit,
                    "sale_unit_price": "310.00",
                    "purchase_unit_price": "255.00",
                    "quantity_value": "4.500",
                    "batch_code": "RESTOCK-060",
                },
            ],
        }
    )
    await product_service.apply_stock_document(db_session, update_payload)

    await db_session.refresh(product_one_before_update)
    await db_session.refresh(product_two_before_update)
    await db_session.refresh(product_sixty_before_update)

    assert product_one_before_update.last_purchase_at == date(2026, 5, 12)
    assert product_one_before_update.last_purchase_price == Decimal("181.00")
    assert product_two_before_update.available_quantity > Decimal("0.000")
    assert product_sixty_before_update.last_purchase_price == Decimal("255.00")
    assert await db_session.scalar(select(func.count(StockDocument.id))) == 3

    courier_user = User(
        full_name="Courier Integration",
        email="courier.integration@example.com",
        phone="+380661234567",
        role=UserRole.COURIER,
        hashed_password="hashed",
    )
    db_session.add(courier_user)
    await db_session.flush()
    courier = Courier(user_id=courier_user.id, vehicle_info="Scooter")
    db_session.add(courier)
    await db_session.commit()

    available_orders = await delivery_service.get_available_orders_for_courier(db_session, limit=50)
    assert len(available_orders) == 25

    first_order = available_orders[0]
    second_order = available_orders[1]

    first_delivery = await delivery_service.self_assign_delivery(
        db_session,
        first_order.id,
        courier_user.id,
        DeliverySelfAssignCreate(),
    )
    assert first_delivery.status == DeliveryStatus.ASSIGNED
    assert first_delivery.order.status == OrderStatus.PREPARING

    courier_deliveries = await delivery_service.get_my_deliveries(db_session, courier.id, limit=50)
    assert len(courier_deliveries) == 1

    picked_up_delivery = await delivery_service.pick_up_delivery(db_session, first_delivery.id, courier.id)
    assert picked_up_delivery.status == DeliveryStatus.PICKED_UP
    assert picked_up_delivery.order.status == OrderStatus.OUT_FOR_DELIVERY

    completed_delivery = await delivery_service.complete_delivery(db_session, first_delivery.id, courier.id)
    assert completed_delivery.status == DeliveryStatus.DELIVERED
    assert completed_delivery.order.status == OrderStatus.DELIVERED

    second_delivery = await delivery_service.self_assign_delivery(
        db_session,
        second_order.id,
        courier_user.id,
        DeliverySelfAssignCreate(),
    )
    await delivery_service.pick_up_delivery(db_session, second_delivery.id, courier.id)
    failed_delivery = await delivery_service.fail_delivery(
        db_session,
        second_delivery.id,
        courier.id,
        DeliveryStatusUpdate(failed_reason="Customer requested a later delivery window"),
    )
    assert failed_delivery.status == DeliveryStatus.FAILED
    assert failed_delivery.order.status == OrderStatus.PREPARING

    completed_product_ids = [item.product_id for item in completed_delivery.order.items if item.product_id is not None]
    failed_product_ids = [item.product_id for item in failed_delivery.order.items if item.product_id is not None]

    for product_id in completed_product_ids:
        refreshed_product = await db_session.scalar(select(Product).where(Product.id == product_id))
        assert refreshed_product is not None
        assert refreshed_product.reserved_quantity == Decimal("0.000")
        assert refreshed_product.stock_on_hand == (
            Decimal(str(refreshed_product.available_quantity or 0))
            + Decimal(str(refreshed_product.reserved_quantity or 0))
        )

    for product_id in failed_product_ids:
        refreshed_product = await db_session.scalar(select(Product).where(Product.id == product_id))
        assert refreshed_product is not None
        assert refreshed_product.reserved_quantity > Decimal("0.000")
