from __future__ import annotations

from collections import OrderedDict
from decimal import Decimal, ROUND_DOWN
from typing import Sequence

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core.time_utils import local_day_range_utc
from core.models import (
    Address,
    Courier,
    Customer,
    Delivery,
    DeliveryStatus,
    Order,
    OrderEventLog,
    OrderItem,
    OrderStatus,
    Product,
    User,
    UserRole,
)
from manage.schemas.auth_schema import phone_number_normalizer
from manage.schemas.order_schema import (
    AdminOrderItemsUpdate,
    AdminPhoneOrderCreate,
    OrderCancelPayload,
    OrderCreate,
)
from manage.services import inventory_service, notification_service, order_event_service

ACTIVE_ORDER_STATUSES = (
    OrderStatus.PLACED,
    OrderStatus.PREPARING,
    OrderStatus.OUT_FOR_DELIVERY,
)

ACTIVE_DELIVERY_STATUSES = (
    DeliveryStatus.ASSIGNED,
    DeliveryStatus.PENDING,
    DeliveryStatus.PICKED_UP,
)

ADMIN_ORDER_DAY_FILTERS: dict[str, tuple[int, int]] = {
    "today": (0, 0),
    "yesterday": (1, 1),
    "day_before_yesterday": (2, 2),
    "today_yesterday": (0, 1),
    "today_to_day_before_yesterday": (0, 2),
    "yesterday_day_before_yesterday": (1, 2),
}


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
        selectinload(Order.events).selectinload(OrderEventLog.actor_user),
    )


async def get_customer_by_user_id(db: AsyncSession, user_id: int) -> Customer:
    result = await db.execute(
        select(Customer)
        .options(selectinload(Customer.user))
        .where(Customer.user_id == user_id)
    )
    customer = result.scalar_one_or_none()
    if not customer:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Профіль покупця не знайдено")
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


async def _load_products_for_update(db: AsyncSession, product_ids: Sequence[int]) -> dict[int, Product]:
    return await inventory_service.get_products_for_update(db, product_ids)


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
    source: str,
    actor_user_id: int | None,
    actor_role: UserRole | None,
    creation_message: str | None = None,
) -> Order:
    order_id: int | None = None

    try:
        if not order_data.items:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="У замовленні має бути хоча б одна позиція")

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
                detail="Ця адреса доставки не належить поточному клієнту",
            )

        merged_items = _merge_order_items(order_data)
        product_ids = [product_id for product_id, _ in merged_items]
        products = await _load_products_for_update(db, product_ids)

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

        out_of_stock_products = [
            product_id
            for product_id, quantity in merged_items
            if Decimal(str(products[product_id].available_quantity or 0)) < quantity
        ]
        if out_of_stock_products:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Insufficient stock for products: {out_of_stock_products}",
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
            inventory_service.reserve_product_quantity(product, quantity)

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
        order_event_service.log_order_event(
            db=db,
            order=order,
            event_type="order_created",
            source=source,
            actor_user_id=actor_user_id,
            actor_role=actor_role,
            previous_order_status=None,
            new_order_status=OrderStatus.PLACED,
            message=creation_message,
        )

        await db.commit()
    except HTTPException:
        await db.rollback()
        raise
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Не вдалося створити замовлення через конфлікт даних")
    except SQLAlchemyError:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Помилка бази даних під час створення замовлення")

    if order_id is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Замовлення не вдалося створити")

    created_order = await get_order_for_admin(db, order_id)
    await notification_service.try_enqueue_new_order_notifications(db, created_order)
    return created_order


async def create_order(db: AsyncSession, user_id: int, order_data: OrderCreate) -> Order:
    customer = await get_customer_by_user_id(db, user_id)
    return await _create_order_for_customer(
        db,
        customer=customer,
        order_data=order_data,
        source="telegram_bot",
        actor_user_id=user_id,
        actor_role=UserRole.CUSTOMER,
        creation_message="Клієнт оформив замовлення через Telegram.",
    )


async def get_order_by_id(db: AsyncSession, user_id: int, order_id: int) -> Order:
    customer = await get_customer_by_user_id(db, user_id)
    result = await db.execute(
        select(Order)
        .options(*_order_relations())
        .where(Order.id == order_id, Order.customer_id == customer.id)
    )
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Замовлення не знайдено")
    return order


async def get_customer_orders(db: AsyncSession, user_id: int, limit: int = 20, offset: int = 0) -> list[Order]:
    customer = await get_customer_by_user_id(db, user_id)
    result = await db.execute(
        select(Order)
        .options(*_order_relations())
        .where(Order.customer_id == customer.id)
        .order_by(Order.placed_at.desc(), Order.id.desc())
        .offset(offset)
        .limit(limit)
    )
    return result.scalars().all()


def _apply_admin_order_filters(
    stmt,
    *,
    status_filter: OrderStatus | None = None,
    queue_filter: str | None = None,
    date_filter: str | None = None,
    search: str | None = None,
):
    if status_filter is not None:
        stmt = stmt.where(Order.status == status_filter)
    if queue_filter == "active":
        stmt = stmt.where(Order.status.in_(ACTIVE_ORDER_STATUSES))
    elif queue_filter == "awaiting_courier":
        stmt = (
            stmt.where(Order.status.in_([OrderStatus.PLACED, OrderStatus.PREPARING]))
            .where(~Order.deliveries.any(Delivery.status.in_(ACTIVE_DELIVERY_STATUSES)))
        )
    elif queue_filter == "with_courier":
        stmt = stmt.where(Order.deliveries.any(Delivery.status.in_(ACTIVE_DELIVERY_STATUSES)))
    elif queue_filter == "completed":
        stmt = stmt.where(Order.status.in_([OrderStatus.DELIVERED, OrderStatus.CANCELLED]))
    elif queue_filter == "problem":
        stmt = stmt.where(Order.deliveries.any(Delivery.status == DeliveryStatus.FAILED))
    if date_filter:
        newest_days_ago, oldest_days_ago = ADMIN_ORDER_DAY_FILTERS[date_filter]
        start_utc, end_utc = local_day_range_utc(
            newest_days_ago=newest_days_ago,
            oldest_days_ago=oldest_days_ago,
        )
        stmt = stmt.where(Order.placed_at >= start_utc, Order.placed_at < end_utc)
    if search:
        search_value = search.strip()
        if search_value:
            term = f"%{search_value}%"
            stmt = (
                stmt.join(Order.customer, isouter=True)
                .join(Customer.user, isouter=True)
                .join(Order.delivery_address, isouter=True)
            )
            filters = [
                User.full_name.ilike(term),
                User.phone.ilike(term),
                User.email.ilike(term),
                Address.street.ilike(term),
                Address.building.ilike(term),
            ]
            if search_value.isdigit():
                filters.append(Order.id == int(search_value))
            stmt = stmt.where(or_(*filters))
    return stmt


async def get_orders_for_admin(
    db: AsyncSession,
    *,
    limit: int = 20,
    offset: int = 0,
    status_filter: OrderStatus | None = None,
    queue_filter: str | None = None,
    date_filter: str | None = None,
    search: str | None = None,
) -> Sequence[Order]:
    stmt = select(Order).options(*_order_relations()).order_by(Order.placed_at.desc(), Order.id.desc())
    stmt = _apply_admin_order_filters(
        stmt,
        status_filter=status_filter,
        queue_filter=queue_filter,
        date_filter=date_filter,
        search=search,
    )
    stmt = stmt.offset(offset).limit(limit)
    result = await db.execute(stmt)
    return result.scalars().all()


async def count_orders_for_admin(
    db: AsyncSession,
    *,
    status_filter: OrderStatus | None = None,
    queue_filter: str | None = None,
    date_filter: str | None = None,
    search: str | None = None,
) -> int:
    stmt = select(func.count(Order.id))
    stmt = _apply_admin_order_filters(
        stmt,
        status_filter=status_filter,
        queue_filter=queue_filter,
        date_filter=date_filter,
        search=search,
    )
    count = await db.scalar(stmt)
    return int(count or 0)


async def get_order_for_admin(db: AsyncSession, order_id: int) -> Order:
    result = await db.execute(
        select(Order)
        .options(*_order_relations())
        .where(Order.id == order_id)
    )
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Замовлення не знайдено")
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
                detail="Цей номер уже прив'язаний до акаунта з іншою роллю",
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
                detail="Цей email уже використовується в іншому акаунті",
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
    *,
    actor_user_id: int | None = None,
    actor_role: UserRole | None = UserRole.ADMIN,
    source: str = "admin_panel",
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
    return await _create_order_for_customer(
        db,
        customer=customer,
        order_data=order_data,
        source=source,
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        creation_message="Менеджер оформив замовлення по дзвінку.",
    )


async def cancel_order_by_admin(
    db: AsyncSession,
    order_id: int,
    payload: OrderCancelPayload,
    *,
    actor_user_id: int | None = None,
    actor_role: UserRole | None = UserRole.ADMIN,
    source: str = "admin_panel",
) -> Order:
    order = await get_order_for_admin(db, order_id)
    previous_order_status = order.status
    courier_users_to_notify: list[User] = []

    if order.status == OrderStatus.DELIVERED:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Доставлене замовлення не можна скасувати")
    if order.status == OrderStatus.CANCELLED:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Замовлення вже скасоване")
    if order.status == OrderStatus.OUT_FOR_DELIVERY:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Замовлення вже передане в доставку, тому скасування з адмінки недоступне",
        )

    active_reason = payload.reason or "Скасовано менеджером"
    for delivery in order.deliveries:
        if delivery.status in {DeliveryStatus.ASSIGNED, DeliveryStatus.PENDING}:
            if delivery.courier is not None and delivery.courier.user is not None:
                courier_users_to_notify.append(delivery.courier.user)
            previous_delivery_status = delivery.status
            delivery.status = DeliveryStatus.FAILED
            delivery.failed_reason = active_reason
            order_event_service.log_order_event(
                db=db,
                order=order,
                delivery_id=delivery.id,
                event_type="delivery_status_changed",
                source=source,
                actor_user_id=actor_user_id,
                actor_role=actor_role,
                previous_delivery_status=previous_delivery_status,
                new_delivery_status=delivery.status,
                message=f"Доставку #{delivery.id} закрито, бо замовлення скасували.",
            )
        elif delivery.status == DeliveryStatus.PICKED_UP:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Кур'єр уже забрав замовлення, тому скасування заблоковане",
            )

    product_ids_to_restock = [item.product_id for item in order.items if item.product_id is not None]
    products_to_restock = await _load_products_for_update(db, product_ids_to_restock)
    for item in order.items:
        if item.product_id is None:
            continue
        product = products_to_restock.get(item.product_id)
        if product is None:
            continue
        inventory_service.release_reserved_quantity(product, _quantize_quantity(Decimal(str(item.quantity))))

    order.status = OrderStatus.CANCELLED
    if payload.reason:
        order.note = (
            f"{order.note}\n\nПричина скасування: {payload.reason}"
            if order.note
            else f"Причина скасування: {payload.reason}"
        )
    order_event_service.log_order_event(
        db=db,
        order=order,
        event_type="order_status_changed",
        source=source,
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        previous_order_status=previous_order_status,
        new_order_status=order.status,
        message=payload.reason or "Менеджер скасував замовлення.",
    )

    try:
        await db.commit()
    except SQLAlchemyError:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Помилка бази даних під час скасування замовлення")

    cancelled_order = await get_order_for_admin(db, order_id)
    await notification_service.try_enqueue_order_status_notifications(
        db,
        order=cancelled_order,
        previous_status=previous_order_status,
        new_status=cancelled_order.status,
        source=source,
    )
    if courier_users_to_notify:
        unique_courier_users = list({user.id: user for user in courier_users_to_notify}.values())
        await notification_service.try_enqueue_courier_order_cancelled_notification(
            db,
            order=cancelled_order,
            courier_users=unique_courier_users,
            reason=active_reason,
        )
    return cancelled_order


def _ensure_order_is_editable(order: Order) -> None:
    if order.status in {OrderStatus.DELIVERED, OrderStatus.CANCELLED, OrderStatus.OUT_FOR_DELIVERY}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Склад замовлення можна змінювати лише до старту доставки",
        )
    for delivery in order.deliveries:
        if delivery.status == DeliveryStatus.PICKED_UP:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Після того як кур'єр забрав замовлення, змінювати позиції вже не можна",
            )


async def update_order_items_by_admin(
    db: AsyncSession,
    order_id: int,
    payload: AdminOrderItemsUpdate,
    *,
    actor_user_id: int | None = None,
    actor_role: UserRole | None = UserRole.ADMIN,
    source: str = "admin_panel",
) -> Order:
    order = await get_order_for_admin(db, order_id)
    _ensure_order_is_editable(order)

    item_map = {item.id: item for item in order.items}
    requested_quantities = {item.item_id: _quantize_quantity(item.quantity) for item in payload.items}
    unknown_item_ids = sorted(set(requested_quantities) - set(item_map))
    if unknown_item_ids:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Не знайдено позиції замовлення: {unknown_item_ids}",
        )

    product_ids = [item.product_id for item in order.items if item.product_id is not None]
    locked_products = await _load_products_for_update(db, product_ids)

    changes: list[str] = []
    remaining_item_count = 0
    total_amount = Decimal("0.00")

    for item in list(order.items):
        current_quantity = _quantize_quantity(Decimal(str(item.quantity)))
        new_quantity = requested_quantities.get(item.id, current_quantity)

        if new_quantity != current_quantity:
            if item.product_id is None or item.product_id not in locked_products:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Неможливо змінити позицію #{item.id}: товар більше недоступний у каталозі",
                )
            product = locked_products[item.product_id]
            delta = new_quantity - current_quantity
            if delta > 0:
                inventory_service.reserve_product_quantity(product, delta)
            elif delta < 0:
                inventory_service.release_reserved_quantity(product, _quantize_quantity(-delta))

        if new_quantity <= 0:
            changes.append(f"{item.product_name}: прибрано із замовлення (було {current_quantity} {item.unit})")
            await db.delete(item)
            continue

        if new_quantity != current_quantity:
            item.quantity = new_quantity
            item.subtotal = _quantize_money(Decimal(str(item.unit_price)) * new_quantity)
            changes.append(f"{item.product_name}: {current_quantity} {item.unit} -> {new_quantity} {item.unit}")

        remaining_item_count += 1
        total_amount += Decimal(str(item.subtotal))

    if remaining_item_count == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Після редагування в замовленні має залишитися хоча б одна позиція",
        )

    if not changes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Кількість у позиціях не змінилася")

    order.total_amount = _quantize_money(total_amount)
    order_event_service.log_order_event(
        db=db,
        order=order,
        event_type="order_items_updated",
        source=source,
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        previous_order_status=order.status,
        new_order_status=order.status,
        message="; ".join(changes),
    )

    try:
        await db.commit()
    except SQLAlchemyError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Помилка бази даних під час оновлення позицій замовлення",
        )

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
        "events": [
            {
                "id": event.id,
                "event_type": event.event_type,
                "source": event.source,
                "actor_user_id": event.actor_user_id,
                "actor_role": event.actor_role.value if event.actor_role else None,
                "actor_name": event.actor_user.full_name if event.actor_user is not None else None,
                "previous_order_status": event.previous_order_status,
                "new_order_status": event.new_order_status,
                "previous_delivery_status": event.previous_delivery_status,
                "new_delivery_status": event.new_delivery_status,
                "message": event.message,
                "created_at": event.created_at,
            }
            for event in order.events
        ],
    }
