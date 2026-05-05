from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from core.models import Address, Customer, Product, ProductBatch, StockDocument, Supplier, User, UserRole
from manage.schemas.order_schema import OrderCreate, OrderItemCreate
from manage.schemas.product_schema import ProductStockDocumentApply
from manage.services import order_service, product_service
from core.models import StockDocumentType


async def _seed_customer_with_address(
    session,
    *,
    full_name: str,
    email: str,
    phone: str,
    street: str,
):
    user = User(
        full_name=full_name,
        email=email,
        phone=phone,
        role=UserRole.CUSTOMER,
        hashed_password="hashed",
    )
    session.add(user)
    await session.flush()

    customer = Customer(user_id=user.id)
    session.add(customer)
    await session.flush()

    address = Address(
        customer_id=customer.id,
        street=street,
        building="10",
        apartment="3",
        notes="call me",
    )
    session.add(address)
    await session.flush()
    return user, address


@pytest.mark.integration
@pytest.mark.asyncio
async def test_receipt_document_creates_supplier_product_batch_and_history(db_session):
    payload = ProductStockDocumentApply.model_validate(
        {
            "document_type": StockDocumentType.RECEIPT,
            "document_number": "REC-2026-05-04-01",
            "document_date": date(2026, 5, 4),
            "supplier_name": "Fresh Sea Supply",
            "supplier_phone": "+380501112233",
            "supplier_email": "supply@example.com",
            "note": "Morning warehouse receipt",
            "items": [
                {
                    "name": "Herring",
                    "unit": "kg",
                    "sale_unit_price": "220.00",
                    "purchase_unit_price": "170.00",
                    "quantity_value": "8.500",
                    "batch_code": "BATCH-HER-01",
                    "expires_at": "2026-05-12",
                }
            ],
        }
    )

    result = await product_service.apply_stock_document(db_session, payload, actor_user_id=None)

    assert result.created_count == 1
    assert result.updated_count == 0
    product = result.touched_products[0]
    assert product.available_quantity == Decimal("8.500")
    assert product.reserved_quantity == Decimal("0.000")
    assert product.last_purchase_price == Decimal("170.00")

    supplier = await db_session.scalar(select(Supplier).where(Supplier.name == "Fresh Sea Supply"))
    document = await db_session.scalar(select(StockDocument).where(StockDocument.document_number == "REC-2026-05-04-01"))
    batch = await db_session.scalar(select(ProductBatch).where(ProductBatch.product_id == product.id))

    assert supplier is not None
    assert document is not None
    assert batch is not None
    assert batch.available_quantity == Decimal("8.500")
    assert batch.original_quantity == Decimal("8.500")
    assert batch.batch_code == "BATCH-HER-01"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_inventory_count_cannot_drop_below_reserved_stock(db_session, monkeypatch):
    monkeypatch.setattr(order_service.notification_service, "try_enqueue_new_order_notifications", AsyncMock())

    user, address = await _seed_customer_with_address(
        db_session,
        full_name="Inventory User",
        email="inventory.user@example.com",
        phone="+380991234567",
        street="Warehouse street",
    )

    product = Product(
        name="Cod",
        sku="RIBA-INV-01",
        description="Atlantic cod",
        image_url=None,
        base_unit_price=Decimal("300.00"),
        last_purchase_price=Decimal("210.00"),
        unit="kg",
        available_quantity=Decimal("5.000"),
        reserved_quantity=Decimal("0.000"),
        is_active=True,
    )
    db_session.add(product)
    await db_session.commit()

    await order_service.create_order(
        db_session,
        user_id=user.id,
        order_data=OrderCreate(
            delivery_address_id=address.id,
            items=[OrderItemCreate(product_id=product.id, quantity=Decimal("2.000"))],
        ),
    )

    payload = ProductStockDocumentApply.model_validate(
        {
            "document_type": StockDocumentType.INVENTORY_COUNT,
            "document_number": "INV-2026-05-04-01",
            "document_date": date(2026, 5, 4),
            "items": [
                {
                    "name": "Cod",
                    "unit": "kg",
                    "quantity_value": "1.000",
                }
            ],
        }
    )

    with pytest.raises(HTTPException) as exc:
        await product_service.apply_stock_document(db_session, payload, actor_user_id=None)

    assert exc.value.status_code == 400
