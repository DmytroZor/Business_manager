from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from core.models import Address, Customer, Order, Product, User, UserRole
from manage.schemas.order_schema import OrderCreate, OrderItemCreate
from manage.services.order_service import create_order


@pytest.mark.integration
@pytest.mark.asyncio
async def test_create_order_rolls_back_when_product_missing(db_session):
    user = User(
        full_name="Order User",
        email="order.user@example.com",
        phone="+380931112233",
        role=UserRole.CUSTOMER,
        hashed_password="hashed",
    )
    db_session.add(user)
    await db_session.flush()

    customer = Customer(user_id=user.id)
    db_session.add(customer)
    await db_session.flush()

    address = Address(
        customer_id=customer.id,
        street="Khreshchatyk",
        building="1",
        apartment="12",
        notes=None,
    )
    db_session.add(address)
    await db_session.commit()

    with pytest.raises(HTTPException) as exc:
        await create_order(
            db_session,
            user_id=user.id,
            order_data=OrderCreate(
                delivery_address_id=address.id,
                items=[OrderItemCreate(product_id=999999, quantity=Decimal("1.000"))],
            ),
        )

    assert exc.value.status_code == 404
    orders = (await db_session.execute(select(Order))).scalars().all()
    assert len(orders) == 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_create_order_success_persists_order_and_items(db_session):
    user = User(
        full_name="Order Success User",
        email="order.success@example.com",
        phone="+380671112233",
        role=UserRole.CUSTOMER,
        hashed_password="hashed",
    )
    db_session.add(user)
    await db_session.flush()

    customer = Customer(user_id=user.id)
    db_session.add(customer)
    await db_session.flush()

    address = Address(
        customer_id=customer.id,
        street="Peremohy",
        building="10",
        apartment="3",
        notes="call me",
    )
    db_session.add(address)

    product = Product(
        name="Salmon",
        sku="RIBA-TEST-01",
        description="Fresh fish",
        base_unit_price=Decimal("100.00"),
        unit="kg",
        is_active=True,
    )
    db_session.add(product)
    await db_session.commit()

    order = await create_order(
        db_session,
        user_id=user.id,
        order_data=OrderCreate(
            delivery_address_id=address.id,
            note="fast delivery",
            items=[OrderItemCreate(product_id=product.id, quantity=Decimal("1.500"))],
        ),
    )

    assert order.id is not None
    assert len(order.items) == 1
    assert order.total_amount == Decimal("150.00")
