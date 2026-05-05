import asyncio
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from core.models import Address, Customer, Order, Product, User, UserRole
from manage.schemas.order_schema import OrderCreate, OrderItemCreate, OrderCancelPayload
from manage.services import order_service


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
async def test_create_order_rolls_back_when_product_missing(db_session, monkeypatch):
    monkeypatch.setattr(order_service.notification_service, "try_enqueue_new_order_notifications", AsyncMock())
    user, address = await _seed_customer_with_address(
        db_session,
        full_name="Order User",
        email="order.user@example.com",
        phone="+380931112233",
        street="Khreshchatyk",
    )
    await db_session.commit()

    with pytest.raises(HTTPException) as exc:
        await order_service.create_order(
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
async def test_create_order_success_persists_order_items_and_reserves_stock(db_session, monkeypatch):
    monkeypatch.setattr(order_service.notification_service, "try_enqueue_new_order_notifications", AsyncMock())
    user, address = await _seed_customer_with_address(
        db_session,
        full_name="Order Success User",
        email="order.success@example.com",
        phone="+380671112233",
        street="Peremohy",
    )

    product = Product(
        name="Salmon",
        sku="RIBA-TEST-01",
        description="Fresh fish",
        image_url="https://example.com/salmon.jpg",
        base_unit_price=Decimal("100.00"),
        unit="kg",
        available_quantity=Decimal("6.000"),
        is_active=True,
    )
    db_session.add(product)
    await db_session.commit()

    order = await order_service.create_order(
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

    await db_session.refresh(product)
    assert product.available_quantity == Decimal("4.500")
    assert product.reserved_quantity == Decimal("1.500")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_cancel_order_restores_product_stock(db_session, monkeypatch):
    monkeypatch.setattr(order_service.notification_service, "try_enqueue_new_order_notifications", AsyncMock())
    user, address = await _seed_customer_with_address(
        db_session,
        full_name="Cancel Flow User",
        email="cancel.flow@example.com",
        phone="+380501010101",
        street="Sichovykh",
    )

    product = Product(
        name="Trout",
        sku="RIBA-TEST-02",
        description="Fresh trout",
        image_url=None,
        base_unit_price=Decimal("80.00"),
        unit="kg",
        available_quantity=Decimal("5.000"),
        is_active=True,
    )
    db_session.add(product)
    await db_session.commit()

    created_order = await order_service.create_order(
        db_session,
        user_id=user.id,
        order_data=OrderCreate(
            delivery_address_id=address.id,
            items=[OrderItemCreate(product_id=product.id, quantity=Decimal("2.000"))],
        ),
    )

    await order_service.cancel_order_by_admin(
        db_session,
        created_order.id,
        payload=OrderCancelPayload(reason="Customer changed mind"),
    )

    await db_session.refresh(product)
    assert product.available_quantity == Decimal("5.000")
    assert product.reserved_quantity == Decimal("0.000")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_concurrent_orders_do_not_oversell_inventory(
    integration_session_maker,
    test_database_url,
    monkeypatch,
):
    if not test_database_url.startswith("postgresql"):
        pytest.skip("Concurrent inventory locking test requires PostgreSQL.")

    monkeypatch.setattr(order_service.notification_service, "try_enqueue_new_order_notifications", AsyncMock())

    async with integration_session_maker() as seed_session:
        customer_a, address_a = await _seed_customer_with_address(
            seed_session,
            full_name="Customer A",
            email="customer.a@example.com",
            phone="+380931111111",
            street="A Street",
        )
        customer_b, address_b = await _seed_customer_with_address(
            seed_session,
            full_name="Customer B",
            email="customer.b@example.com",
            phone="+380932222222",
            street="B Street",
        )
        product = Product(
            name="Sea bass",
            sku="RIBA-LOCK-01",
            description="Shared stock",
            image_url=None,
            base_unit_price=Decimal("120.00"),
            unit="kg",
            available_quantity=Decimal("5.000"),
            is_active=True,
        )
        seed_session.add(product)
        await seed_session.commit()
        product_id = product.id
        customer_a_id = customer_a.id
        customer_b_id = customer_b.id
        address_a_id = address_a.id
        address_b_id = address_b.id

    start_event = asyncio.Event()

    async def _place_order(user_id: int, address_id: int):
        async with integration_session_maker() as session:
            await start_event.wait()
            return await order_service.create_order(
                session,
                user_id=user_id,
                order_data=OrderCreate(
                    delivery_address_id=address_id,
                    items=[OrderItemCreate(product_id=product_id, quantity=Decimal("3.000"))],
                ),
            )

    task_one = asyncio.create_task(_place_order(customer_a_id, address_a_id))
    task_two = asyncio.create_task(_place_order(customer_b_id, address_b_id))
    start_event.set()

    results = await asyncio.gather(task_one, task_two, return_exceptions=True)
    failures = [result for result in results if isinstance(result, Exception)]
    successes = [result for result in results if not isinstance(result, Exception)]

    assert len(successes) == 1
    assert len(failures) == 1
    assert isinstance(failures[0], HTTPException)
    assert failures[0].status_code == 409

    async with integration_session_maker() as verification_session:
        remaining_stock = await verification_session.scalar(
            select(Product.available_quantity).where(Product.id == product_id)
        )
        reserved_stock = await verification_session.scalar(
            select(Product.reserved_quantity).where(Product.id == product_id)
        )
        total_orders = await verification_session.scalar(select(func.count(Order.id)))

    assert remaining_stock == Decimal("2.000")
    assert reserved_stock == Decimal("3.000")
    assert total_orders == 1
