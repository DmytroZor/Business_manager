from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from core.models import Address, Customer, Courier, Delivery, DeliveryStatus, Order, OrderStatus, Product, User, UserRole
from manage.schemas.delivery_schema import DeliverySelfAssignCreate
from manage.schemas.order_schema import OrderCreate, OrderItemCreate
from manage.services.delivery_service import get_available_orders_for_courier, self_assign_delivery
from manage.services.order_service import create_order


@pytest.mark.integration
@pytest.mark.asyncio
async def test_self_assign_delivery_creates_assigned_delivery(db_session):
    customer_user = User(
        full_name="Customer",
        email="customer.delivery@example.com",
        phone="+380991112233",
        role=UserRole.CUSTOMER,
        hashed_password="hashed",
    )
    courier_user = User(
        full_name="Courier",
        email="courier.delivery@example.com",
        phone="+380661112233",
        role=UserRole.COURIER,
        hashed_password="hashed",
    )
    db_session.add_all([customer_user, courier_user])
    await db_session.flush()

    customer = Customer(user_id=customer_user.id)
    courier = Courier(user_id=courier_user.id)
    db_session.add_all([customer, courier])
    await db_session.flush()

    address = Address(customer_id=customer.id, street="Naukova", building="1", apartment="2", notes=None)
    product = Product(
        name="Carp",
        sku="RIBA-DELIVERY-01",
        description="Fresh carp",
        base_unit_price=Decimal("50.00"),
        unit="kg",
        is_active=True,
    )
    db_session.add_all([address, product])
    await db_session.commit()

    order = await create_order(
        db_session,
        user_id=customer_user.id,
        order_data=OrderCreate(
            delivery_address_id=address.id,
            items=[OrderItemCreate(product_id=product.id, quantity=Decimal("1.000"))],
        ),
    )

    delivery = await self_assign_delivery(
        db_session,
        order.id,
        courier_user.id,
        DeliverySelfAssignCreate(),
    )

    delivery_in_db = (await db_session.execute(select(Delivery).where(Delivery.id == delivery.id))).scalar_one()
    order_in_db = (await db_session.execute(select(Order).where(Order.id == order.id))).scalar_one()

    assert delivery_in_db.status == DeliveryStatus.ASSIGNED
    assert delivery_in_db.courier_id == courier.id
    assert order_in_db.status == OrderStatus.PREPARING


@pytest.mark.integration
@pytest.mark.asyncio
async def test_available_orders_excludes_orders_with_active_delivery(db_session):
    customer_user = User(
        full_name="Customer 2",
        email="customer2.delivery@example.com",
        phone="+380991112244",
        role=UserRole.CUSTOMER,
        hashed_password="hashed",
    )
    courier_user = User(
        full_name="Courier 2",
        email="courier2.delivery@example.com",
        phone="+380661112244",
        role=UserRole.COURIER,
        hashed_password="hashed",
    )
    db_session.add_all([customer_user, courier_user])
    await db_session.flush()

    customer = Customer(user_id=customer_user.id)
    courier = Courier(user_id=courier_user.id)
    db_session.add_all([customer, courier])
    await db_session.flush()

    address = Address(customer_id=customer.id, street="Soborna", building="7", apartment=None, notes=None)
    product = Product(
        name="Pike",
        sku="RIBA-DELIVERY-02",
        description="Fresh pike",
        base_unit_price=Decimal("75.00"),
        unit="kg",
        is_active=True,
    )
    db_session.add_all([address, product])
    await db_session.commit()

    order = await create_order(
        db_session,
        user_id=customer_user.id,
        order_data=OrderCreate(
            delivery_address_id=address.id,
            items=[OrderItemCreate(product_id=product.id, quantity=Decimal("2.000"))],
        ),
    )

    available_before = await get_available_orders_for_courier(db_session)
    assert [item.id for item in available_before] == [order.id]

    await self_assign_delivery(
        db_session,
        order.id,
        courier_user.id,
        DeliverySelfAssignCreate(),
    )

    available_after = await get_available_orders_for_courier(db_session)
    assert available_after == []


@pytest.mark.integration
@pytest.mark.asyncio
async def test_self_assign_delivery_rejects_order_with_existing_active_delivery(db_session):
    customer_user = User(
        full_name="Customer 3",
        email="customer3.delivery@example.com",
        phone="+380991112255",
        role=UserRole.CUSTOMER,
        hashed_password="hashed",
    )
    courier_user = User(
        full_name="Courier 3",
        email="courier3.delivery@example.com",
        phone="+380661112255",
        role=UserRole.COURIER,
        hashed_password="hashed",
    )
    second_courier_user = User(
        full_name="Courier 4",
        email="courier4.delivery@example.com",
        phone="+380661112266",
        role=UserRole.COURIER,
        hashed_password="hashed",
    )
    db_session.add_all([customer_user, courier_user, second_courier_user])
    await db_session.flush()

    customer = Customer(user_id=customer_user.id)
    courier = Courier(user_id=courier_user.id)
    second_courier = Courier(user_id=second_courier_user.id)
    db_session.add_all([customer, courier, second_courier])
    await db_session.flush()

    address = Address(customer_id=customer.id, street="Dniprovska", building="15", apartment=None, notes=None)
    product = Product(
        name="Perch",
        sku="RIBA-DELIVERY-03",
        description="Fresh perch",
        base_unit_price=Decimal("40.00"),
        unit="kg",
        is_active=True,
    )
    db_session.add_all([address, product])
    await db_session.commit()

    order = await create_order(
        db_session,
        user_id=customer_user.id,
        order_data=OrderCreate(
            delivery_address_id=address.id,
            items=[OrderItemCreate(product_id=product.id, quantity=Decimal("1.000"))],
        ),
    )

    await self_assign_delivery(
        db_session,
        order.id,
        courier_user.id,
        DeliverySelfAssignCreate(),
    )

    with pytest.raises(HTTPException) as exc:
        await self_assign_delivery(
            db_session,
            order.id,
            second_courier_user.id,
            DeliverySelfAssignCreate(),
        )

    assert exc.value.status_code == 409
