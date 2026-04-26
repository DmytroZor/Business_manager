from __future__ import annotations

from collections import OrderedDict
from decimal import Decimal, ROUND_DOWN
from typing import Iterable, Sequence

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core.models import (
    Address,
    Courier,
    Customer,
    Delivery,
    DeliveryStatus,
    Order,
    OrderItem,
    OrderStatus,
    Product,
    User,
    UserRole,
)
from manage.schemas.auth_schema import phone_number_normalizer
from manage.schemas.order_schema import AdminPhoneOrderCreate, OrderCreate, OrderCancelPayload


def _quantize_money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_DOWN)


def _quantize_quantity(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.001"), rounding=ROUND_DOWN)


def _order_relations():
    return (
        selectinload(Order.items),
        selectinload(Order.customer).selectinload(Customer.user),
        selectinload(Order.delivery_address),
        selectinload(Order.deliveries).selectinload(Delivery.courier).selectinload(Courier.user),
    )


async def get_customer_by_user_id(db: AsyncSession, user_id: int) -> Customer:
    result = await db.execute(
        select(Customer)
        .options(selectinload(Customer.user))
        .where(Customer.user_id == user_id)
    )
    customer = result.scalar_one_or_none()
    if not customer:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Customer profile not found")
    return customer


def _merge_order_items(order_data: OrderCreate) -> list[tuple[int, Decimal]]:
    merged: OrderedDict[int, Decimal] = OrderedDict()

    for item in order_data.items:
        quantity = _quantize_quantity(item.quantity)
        if item.product_id in merged:
            merged[item.product_id] = _quantize_quantity(merged[item.product_id] + quantity)
        else:
            merged[item.product_id] = quantity

    return list(merged.items())


def _active_delivery(order: Order) -> Delivery | None:
    if not order.deliveries:
        return None

    priorities = {
        DeliveryStatus.PICKED_UP: 4,
        DeliveryStatus.ASSIGNED: 3,
        DeliveryStatus.PENDING: 2,
        DeliveryStatus.DELIVERED: 1,
        DeliveryStatus.FAILED: 0,
    }
    return max(
        order.deliveries,
        key=lambda delivery: (
            priorities.get(delivery.status, -1),
            delivery.created_at or delivery.assigned_at,
        ),
    )


async def _create_order_for_customer(
    db: AsyncSession,
    *,
    customer: Customer,
    order_data: OrderCreate,
) -> Order:
    order_id: int | None = None

    try:
        if not order_data.items:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Order must contain at least one item")

        address_result = await db.execute(
            select(Address).where(
                Address.id == order_data.delivery_address_id,
                Address.customer_id == customer.id,
            )
        )
        address = address_result.scalar_one_or_none()
        if not address:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Delivery address does not belong to the customer",
            )

        merged_items = _merge_order_items(order_data)
        product_ids = [product_id for product_id, _ in merged_items]

        products_result = await db.execute(select(Product).where(Product.id.in_(product_ids)))
        products = {product.id: product for product in products_result.scalars().all()}

        missing_products = [product_id for product_id in product_ids if product_id not in products]
        if missing_products:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Products not found: {missing_products}",
            )

        inactive_products = [product_id for product_id in product_ids if not products[product_id].is_active]
        if inactive_products:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Inactive products in order: {inactive_products}",
            )

        order = Order(
            customer_id=customer.id,
            delivery_address_id=order_data.delivery_address_id,
            note=order_data.note,
            status=OrderStatus.PLACED,
            total_amount=Decimal("0.00"),
        )
        db.add(order)
        await db.flush()
        order_id = order.id

        total_amount = Decimal("0.00")

        for product_id, quantity in merged_items:
            product = products[product_id]
            unit_price = _quantize_money(Decimal(str(product.base_unit_price)))
            subtotal = _quantize_money(unit_price * quantity)

            order_item = OrderItem(
                order_id=order.id,
                product_id=product.id,
                product_name=product.name,
                product_sku=product.sku,
                unit=product.unit,
                unit_price=unit_price,
                quantity=quantity,
                subtotal=subtotal,
            )
            db.add(order_item)
            total_amount += subtotal

        order.total_amount = _quantize_money(total_amount)

        await db.commit()

    except HTTPException:
        await db.rollback()
        raise
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Database integrity error while creating order")
    except SQLAlchemyError:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Database error while creating order")

    if order_id is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Order was not created")

    return await get_order_for_admin(db, order_id)


async def create_order(db: AsyncSession, user_id: int, order_data: OrderCreate) -> Order:
    customer = await get_customer_by_user_id(db, user_id)
    return await _create_order_for_customer(db, customer=customer, order_data=order_data)


async def get_order_by_id(db: AsyncSession, user_id: int, order_id: int) -> Order:
    customer = await get_customer_by_user_id(db, user_id)
    result = await db.execute(
        select(Order)
        .options(*_order_relations())
        .where(Order.id == order_id, Order.customer_id == customer.id)
    )
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    return order


async def get_customer_orders(db: AsyncSession, user_id: int, limit: int = 20, offset: int = 0) -> list[Order]:
    customer = await get_customer_by_user_id(db, user_id)
    result = await db.execute(
        select(Order)
        .options(*_order_relations())
        .where(Order.customer_id == customer.id)
        .order_by(Order.placed_at.desc())
        .offset(offset)
        .limit(limit)
    )
    return result.scalars().all()


async def get_orders_for_admin(
    db: AsyncSession,
    *,
    limit: int = 20,
    offset: int = 0,
    status_filter: OrderStatus | None = None,
) -> Sequence[Order]:
    stmt = (
        select(Order)
        .options(*_order_relations())
        .order_by(Order.placed_at.desc())
        .offset(offset)
        .limit(limit)
    )
    if status_filter is not None:
        stmt = stmt.where(Order.status == status_filter)

    result = await db.execute(stmt)
    return result.scalars().all()


async def get_order_for_admin(db: AsyncSession, order_id: int) -> Order:
    result = await db.execute(
        select(Order)
        .options(*_order_relations())
        .where(Order.id == order_id)
    )
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    return order


async def _get_or_create_customer_for_phone_order(
    db: AsyncSession,
    payload: AdminPhoneOrderCreate,
) -> Customer:
    normalized_phone = phone_number_normalizer(payload.customer_phone_number)

    existing_user_result = await db.execute(
        select(User)
        .options(selectinload(User.customer_profile))
        .where(User.phone == normalized_phone)
    )
    existing_user = existing_user_result.scalar_one_or_none()

    if existing_user is not None:
        if existing_user.role != UserRole.CUSTOMER or existing_user.customer_profile is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This phone number belongs to a non-customer account",
            )
        if payload.customer_email and existing_user.email is None:
            existing_user.email = payload.customer_email
        if payload.customer_full_name:
            existing_user.full_name = payload.customer_full_name
        await db.flush()
        return existing_user.customer_profile

    if payload.customer_email:
        existing_email = await db.execute(select(User.id).where(User.email == payload.customer_email))
        if existing_email.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This email already belongs to another account",
            )

    user = User(
        full_name=payload.customer_full_name,
        phone=normalized_phone,
        email=payload.customer_email,
        hashed_password=None,
        role=UserRole.CUSTOMER,
        is_active=True,
    )
    db.add(user)
    await db.flush()

    customer = Customer(user_id=user.id)
    db.add(customer)
    await db.flush()
    return customer


async def _get_or_create_address_for_customer(
    db: AsyncSession,
    *,
    customer_id: int,
    street: str,
    building: str,
    apartment: str | None,
    notes: str | None,
) -> Address:
    result = await db.execute(
        select(Address).where(
            Address.customer_id == customer_id,
            Address.street == street,
            Address.building == building,
            Address.apartment == apartment,
        )
    )
    address = result.scalar_one_or_none()
    if address is not None:
        if notes:
            address.notes = notes
        await db.flush()
        return address

    address = Address(
        customer_id=customer_id,
        street=street,
        building=building,
        apartment=apartment,
        notes=notes,
    )
    db.add(address)
    await db.flush()
    return address


async def create_phone_order_by_admin(
    db: AsyncSession,
    payload: AdminPhoneOrderCreate,
) -> Order:
    customer = await _get_or_create_customer_for_phone_order(db, payload)
    address = await _get_or_create_address_for_customer(
        db,
        customer_id=customer.id,
        street=payload.street,
        building=payload.building,
        apartment=payload.apartment,
        notes=payload.address_notes,
    )
    order_data = OrderCreate(
        delivery_address_id=address.id,
        note=payload.note,
        items=payload.items,
    )
    return await _create_order_for_customer(db, customer=customer, order_data=order_data)


async def cancel_order_by_admin(
    db: AsyncSession,
    order_id: int,
    payload: OrderCancelPayload,
) -> Order:
    order = await get_order_for_admin(db, order_id)

    if order.status == OrderStatus.DELIVERED:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Delivered order cannot be cancelled")
    if order.status == OrderStatus.CANCELLED:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Order is already cancelled")
    if order.status == OrderStatus.OUT_FOR_DELIVERY:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Order is already out for delivery and cannot be cancelled from admin flow",
        )

    active_reason = payload.reason or "Cancelled by manager"
    for delivery in order.deliveries:
        if delivery.status in {DeliveryStatus.ASSIGNED, DeliveryStatus.PENDING}:
            delivery.status = DeliveryStatus.FAILED
            delivery.failed_reason = active_reason
        elif delivery.status == DeliveryStatus.PICKED_UP:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Courier already picked up the order; cancellation is blocked",
            )

    order.status = OrderStatus.CANCELLED
    if payload.reason:
        order.note = f"{order.note}\n\nCancellation reason: {payload.reason}" if order.note else f"Cancellation reason: {payload.reason}"

    try:
        await db.commit()
    except SQLAlchemyError:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Database error while cancelling order")

    return await get_order_for_admin(db, order_id)


def build_admin_order_payload(order: Order) -> dict:
    customer = None
    if order.customer is not None and order.customer.user is not None:
        user = order.customer.user
        customer = {
            "user_id": user.id,
            "customer_id": order.customer.id,
            "full_name": user.full_name,
            "phone": user.phone,
            "email": user.email,
        }

    delivery_address = None
    if order.delivery_address is not None:
        address = order.delivery_address
        delivery_address = {
            "id": address.id,
            "street": address.street,
            "building": address.building,
            "apartment": address.apartment,
            "notes": address.notes,
        }

    active_delivery = None
    current_delivery = _active_delivery(order)
    if current_delivery is not None:
        courier_info = None
        if current_delivery.courier is not None and current_delivery.courier.user is not None:
            courier_user = current_delivery.courier.user
            courier_info = {
                "courier_id": current_delivery.courier.id,
                "user_id": courier_user.id,
                "full_name": courier_user.full_name,
                "phone": courier_user.phone,
                "telegram_id": courier_user.telegram_id,
            }
        active_delivery = {
            "id": current_delivery.id,
            "status": current_delivery.status,
            "scheduled_at": current_delivery.scheduled_at,
            "assigned_at": current_delivery.assigned_at,
            "picked_up_at": current_delivery.picked_up_at,
            "delivered_at": current_delivery.delivered_at,
            "failed_reason": current_delivery.failed_reason,
            "fee": current_delivery.fee,
            "courier": courier_info,
        }

    return {
        "id": order.id,
        "status": order.status,
        "placed_at": order.placed_at,
        "total_amount": order.total_amount,
        "note": order.note,
        "customer": customer,
        "delivery_address": delivery_address,
        "items": list(order.items),
        "active_delivery": active_delivery,
    }
