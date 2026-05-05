from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Sequence

from fastapi import HTTPException, status
from sqlalchemy import desc, exists, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core.time_utils import local_day_range_utc
from core.models import Courier, Customer, Delivery, DeliveryStatus, Order, OrderStatus, UserRole
from manage.schemas.delivery_schema import DeliveryAssignCreate, DeliverySelfAssignCreate, DeliveryStatusUpdate
from manage.services import inventory_service, notification_service, order_event_service, order_service


async def _get_order(db: AsyncSession, order_id: int) -> Order:
    stmt = (
        select(Order)
        .options(
            selectinload(Order.deliveries),
            selectinload(Order.items),
            selectinload(Order.customer).selectinload(Customer.user),
            selectinload(Order.delivery_address),
        )
        .where(Order.id == order_id)
    )
    result = await db.execute(stmt)
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Замовлення не знайдено")
    return order


async def _get_courier_by_id(db: AsyncSession, courier_id: int) -> Courier:
    stmt = (
        select(Courier)
        .options(selectinload(Courier.user))
        .where(Courier.id == courier_id)
    )
    result = await db.execute(stmt)
    courier = result.scalar_one_or_none()
    if not courier:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Кур'єра не знайдено")
    return courier


async def _get_courier_by_user_id(db: AsyncSession, user_id: int) -> Courier:
    stmt = (
        select(Courier)
        .options(selectinload(Courier.user))
        .where(Courier.user_id == user_id)
    )
    result = await db.execute(stmt)
    courier = result.scalar_one_or_none()
    if not courier:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Профіль кур'єра не знайдено")
    return courier


async def _get_delivery(db: AsyncSession, delivery_id: int) -> Delivery:
    stmt = (
        select(Delivery)
        .options(
            selectinload(Delivery.order).selectinload(Order.items),
            selectinload(Delivery.order).selectinload(Order.customer).selectinload(Customer.user),
            selectinload(Delivery.order).selectinload(Order.delivery_address),
            selectinload(Delivery.courier).selectinload(Courier.user),
        )
        .where(Delivery.id == delivery_id)
    )
    result = await db.execute(stmt)
    delivery = result.scalar_one_or_none()
    if not delivery:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Доставку не знайдено")
    return delivery


def _build_courier_order_payload(order: Order) -> dict:
    if isinstance(order, dict):
        return order

    customer = None
    if order.customer is not None and order.customer.user is not None:
        customer = {
            "full_name": order.customer.user.full_name,
            "phone": order.customer.user.phone,
        }

    delivery_address = None
    if order.delivery_address is not None:
        delivery_address = {
            "street": order.delivery_address.street,
            "building": order.delivery_address.building,
            "apartment": order.delivery_address.apartment,
            "notes": order.delivery_address.notes,
        }

    return {
        "id": order.id,
        "status": order.status,
        "placed_at": order.placed_at,
        "total_amount": order.total_amount,
        "note": order.note,
        "delivery_address": delivery_address,
        "customer": customer,
        "items": list(order.items),
    }


def build_available_order_payload(order: Order) -> dict:
    return _build_courier_order_payload(order)


def build_delivery_payload(delivery: Delivery) -> dict:
    if isinstance(delivery, dict):
        return delivery

    courier = None
    if delivery.courier is not None and delivery.courier.user is not None:
        courier = {
            "full_name": delivery.courier.user.full_name,
            "phone": delivery.courier.user.phone,
            "vehicle_info": delivery.courier.vehicle_info,
        }

    return {
        "id": delivery.id,
        "order_id": delivery.order_id,
        "courier_id": delivery.courier_id,
        "status": delivery.status,
        "scheduled_at": delivery.scheduled_at,
        "assigned_at": delivery.assigned_at,
        "picked_up_at": delivery.picked_up_at,
        "delivered_at": delivery.delivered_at,
        "failed_reason": delivery.failed_reason,
        "fee": delivery.fee,
        "created_at": delivery.created_at,
        "order": _build_courier_order_payload(delivery.order) if delivery.order is not None else None,
        "courier": courier,
    }


def _validate_courier_for_assignment(courier: Courier) -> None:
    if courier.user.role != UserRole.COURIER:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Обраний користувач не має ролі кур'єра",
        )

    if not courier.user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Акаунт кур'єра неактивний",
        )


def _validate_order_status(order: Order) -> None:
    if order.status not in {OrderStatus.PLACED, OrderStatus.PREPARING}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Для поточного статусу замовлення призначення доставки недоступне",
        )


async def _ensure_no_active_delivery(db: AsyncSession, order_id: int) -> None:
    active_delivery_statuses = {
        DeliveryStatus.ASSIGNED,
        DeliveryStatus.PENDING,
        DeliveryStatus.PICKED_UP,
    }
    active_delivery_stmt = select(Delivery.id).where(
        Delivery.order_id == order_id,
        Delivery.status.in_(list(active_delivery_statuses)),
    )
    active_delivery_result = await db.execute(active_delivery_stmt)
    if active_delivery_result.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Для цього замовлення вже є активна доставка",
        )


async def _create_assigned_delivery(
    db: AsyncSession,
    *,
    order: Order,
    courier: Courier,
    scheduled_at: datetime | None,
    fee,
    actor_user_id: int | None,
    actor_role: UserRole | None,
    source: str,
) -> Delivery:
    _validate_courier_for_assignment(courier)
    _validate_order_status(order)
    await _ensure_no_active_delivery(db, order.id)

    previous_order_status = order.status
    delivery = Delivery(
        order_id=order.id,
        courier_id=courier.id,
        status=DeliveryStatus.ASSIGNED,
        scheduled_at=scheduled_at,
        assigned_at=datetime.now(timezone.utc),
        fee=fee,
    )

    order.status = OrderStatus.PREPARING
    db.add(delivery)
    await db.flush()

    order_event_service.log_order_event(
        db=db,
        order=order,
        delivery_id=delivery.id,
        event_type="delivery_assigned",
        source=source,
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        previous_delivery_status=None,
        new_delivery_status=delivery.status,
        message=f"Кур'єра {courier.user.full_name} призначено на це замовлення.",
    )
    order_event_service.log_order_event(
        db=db,
        order=order,
        delivery_id=delivery.id,
        event_type="order_status_changed",
        source=source,
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        previous_order_status=previous_order_status,
        new_order_status=order.status,
        message="Замовлення перейшло в підготовку після призначення кур'єра.",
    )

    await db.commit()
    await db.refresh(delivery)

    refreshed_order = await order_service.get_order_for_admin(db, order.id)
    should_notify_courier = not (
        actor_role == UserRole.COURIER
        and actor_user_id == courier.user_id
        and source == "telegram_bot"
    )
    if courier.user is not None and should_notify_courier:
        await notification_service.try_enqueue_delivery_assigned_notification(
            db,
            order=refreshed_order,
            delivery=delivery,
            courier_user=courier.user,
        )
    await notification_service.try_enqueue_order_status_notifications(
        db,
        order=refreshed_order,
        previous_status=previous_order_status,
        new_status=refreshed_order.status,
        source=source,
        delivery=delivery,
    )
    return delivery


async def assign_delivery(
    db: AsyncSession,
    order_id: int,
    payload: DeliveryAssignCreate,
    *,
    actor_user_id: int | None = None,
    actor_role: UserRole | None = UserRole.ADMIN,
    source: str = "admin_api",
) -> Delivery:
    order = await _get_order(db, order_id)
    courier = await _get_courier_by_id(db, payload.courier_id)
    return await _create_assigned_delivery(
        db,
        order=order,
        courier=courier,
        scheduled_at=payload.scheduled_at,
        fee=payload.fee,
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        source=source,
    )


async def get_available_orders_for_courier(
    db: AsyncSession,
    *,
    limit: int = 20,
    offset: int = 0,
) -> Sequence[Order]:
    start_utc, end_utc = local_day_range_utc(newest_days_ago=0, oldest_days_ago=0)
    active_delivery_exists = exists().where(
        Delivery.order_id == Order.id,
        Delivery.status.in_(
            [DeliveryStatus.ASSIGNED, DeliveryStatus.PENDING, DeliveryStatus.PICKED_UP]
        ),
    )
    stmt = (
        select(Order)
        .options(
            selectinload(Order.items),
            selectinload(Order.customer).selectinload(Customer.user),
            selectinload(Order.delivery_address),
        )
        .where(Order.status.in_([OrderStatus.PLACED, OrderStatus.PREPARING]))
        .where(Order.placed_at >= start_utc, Order.placed_at < end_utc)
        .where(~active_delivery_exists)
        .order_by(desc(Order.placed_at), desc(Order.id))
        .limit(limit)
        .offset(offset)
    )
    result = await db.execute(stmt)
    return result.scalars().all()


async def self_assign_delivery(
    db: AsyncSession,
    order_id: int,
    courier_user_id: int,
    payload: DeliverySelfAssignCreate,
) -> Delivery:
    order = await _get_order(db, order_id)
    courier = await _get_courier_by_user_id(db, courier_user_id)
    return await _create_assigned_delivery(
        db,
        order=order,
        courier=courier,
        scheduled_at=payload.scheduled_at,
        fee=payload.fee,
        actor_user_id=courier_user_id,
        actor_role=UserRole.COURIER,
        source="telegram_bot",
    )


async def get_delivery_by_id(db: AsyncSession, delivery_id: int) -> Delivery:
    return await _get_delivery(db, delivery_id)


async def get_my_deliveries(
    db: AsyncSession,
    courier_id: int,
    *,
    status_filter: Optional[DeliveryStatus] = None,
    limit: int = 20,
    offset: int = 0,
) -> Sequence[Delivery]:
    stmt = (
        select(Delivery)
        .options(
            selectinload(Delivery.order).selectinload(Order.items),
            selectinload(Delivery.order).selectinload(Order.customer).selectinload(Customer.user),
            selectinload(Delivery.order).selectinload(Order.delivery_address),
            selectinload(Delivery.courier).selectinload(Courier.user),
        )
        .where(Delivery.courier_id == courier_id)
        .order_by(desc(Delivery.created_at))
        .limit(limit)
        .offset(offset)
    )
    if status_filter is not None:
        stmt = stmt.where(Delivery.status == status_filter)

    result = await db.execute(stmt)
    return result.scalars().all()


async def pick_up_delivery(
    db: AsyncSession,
    delivery_id: int,
    courier_id: int,
    *,
    source: str = "telegram_bot",
) -> Delivery:
    delivery = await _get_delivery(db, delivery_id)

    if delivery.courier_id != courier_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Ця доставка закріплена за іншим кур'єром")

    if delivery.status not in {DeliveryStatus.ASSIGNED, DeliveryStatus.PENDING}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="У поточному статусі цю доставку не можна позначити як забрану",
        )

    previous_delivery_status = delivery.status
    previous_order_status = delivery.order.status
    await inventory_service.consume_order_stock_for_pickup(db, delivery.order)
    delivery.status = DeliveryStatus.PICKED_UP
    delivery.picked_up_at = datetime.now(timezone.utc)
    delivery.order.status = OrderStatus.OUT_FOR_DELIVERY
    order_event_service.log_order_event(
        db=db,
        order=delivery.order,
        delivery_id=delivery.id,
        event_type="delivery_status_changed",
        source=source,
        actor_user_id=delivery.courier.user_id if delivery.courier else None,
        actor_role=UserRole.COURIER,
        previous_delivery_status=previous_delivery_status,
        new_delivery_status=delivery.status,
        message="Кур'єр забрав замовлення.",
    )
    order_event_service.log_order_event(
        db=db,
        order=delivery.order,
        delivery_id=delivery.id,
        event_type="order_status_changed",
        source=source,
        actor_user_id=delivery.courier.user_id if delivery.courier else None,
        actor_role=UserRole.COURIER,
        previous_order_status=previous_order_status,
        new_order_status=delivery.order.status,
        message="Замовлення передано в доставку.",
    )

    await db.commit()
    await db.refresh(delivery)

    refreshed_order = await order_service.get_order_for_admin(db, delivery.order_id)
    await notification_service.try_enqueue_order_status_notifications(
        db,
        order=refreshed_order,
        previous_status=previous_order_status,
        new_status=refreshed_order.status,
        source=source,
        delivery=delivery,
    )
    return delivery


async def complete_delivery(
    db: AsyncSession,
    delivery_id: int,
    courier_id: int,
    *,
    source: str = "telegram_bot",
) -> Delivery:
    delivery = await _get_delivery(db, delivery_id)

    if delivery.courier_id != courier_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Ця доставка закріплена за іншим кур'єром")

    if delivery.status != DeliveryStatus.PICKED_UP:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Завершити можна лише ту доставку, яку кур'єр уже забрав",
        )

    previous_delivery_status = delivery.status
    previous_order_status = delivery.order.status
    delivery.status = DeliveryStatus.DELIVERED
    delivery.delivered_at = datetime.now(timezone.utc)
    delivery.order.status = OrderStatus.DELIVERED
    order_event_service.log_order_event(
        db=db,
        order=delivery.order,
        delivery_id=delivery.id,
        event_type="delivery_status_changed",
        source=source,
        actor_user_id=delivery.courier.user_id if delivery.courier else None,
        actor_role=UserRole.COURIER,
        previous_delivery_status=previous_delivery_status,
        new_delivery_status=delivery.status,
        message="Кур'єр завершив доставку.",
    )
    order_event_service.log_order_event(
        db=db,
        order=delivery.order,
        delivery_id=delivery.id,
        event_type="order_status_changed",
        source=source,
        actor_user_id=delivery.courier.user_id if delivery.courier else None,
        actor_role=UserRole.COURIER,
        previous_order_status=previous_order_status,
        new_order_status=delivery.order.status,
        message="Замовлення позначено як доставлене.",
    )

    await db.commit()
    await db.refresh(delivery)

    refreshed_order = await order_service.get_order_for_admin(db, delivery.order_id)
    await notification_service.try_enqueue_order_status_notifications(
        db,
        order=refreshed_order,
        previous_status=previous_order_status,
        new_status=refreshed_order.status,
        source=source,
        delivery=delivery,
    )
    return delivery


async def fail_delivery(
    db: AsyncSession,
    delivery_id: int,
    courier_id: int,
    payload: DeliveryStatusUpdate,
    *,
    source: str = "telegram_bot",
) -> Delivery:
    delivery = await _get_delivery(db, delivery_id)

    if delivery.courier_id != courier_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Ця доставка закріплена за іншим кур'єром")

    if delivery.status not in {DeliveryStatus.ASSIGNED, DeliveryStatus.PICKED_UP}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Для цього статусу не можна позначити збій доставки",
        )

    if not payload.failed_reason:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Потрібно вказати причину збою доставки",
        )

    previous_delivery_status = delivery.status
    previous_order_status = delivery.order.status
    if previous_delivery_status == DeliveryStatus.PICKED_UP:
        await inventory_service.restore_pickup_to_reserved(db, delivery.order)
    delivery.status = DeliveryStatus.FAILED
    delivery.failed_reason = payload.failed_reason
    delivery.order.status = OrderStatus.PREPARING
    order_event_service.log_order_event(
        db=db,
        order=delivery.order,
        delivery_id=delivery.id,
        event_type="delivery_status_changed",
        source=source,
        actor_user_id=delivery.courier.user_id if delivery.courier else None,
        actor_role=UserRole.COURIER,
        previous_delivery_status=previous_delivery_status,
        new_delivery_status=delivery.status,
        message=f"Кур'єр повідомив про збій доставки: {payload.failed_reason}",
    )
    order_event_service.log_order_event(
        db=db,
        order=delivery.order,
        delivery_id=delivery.id,
        event_type="order_status_changed",
        source=source,
        actor_user_id=delivery.courier.user_id if delivery.courier else None,
        actor_role=UserRole.COURIER,
        previous_order_status=previous_order_status,
        new_order_status=delivery.order.status,
        message="Після збою доставки замовлення повернули в підготовку.",
    )

    await db.commit()
    await db.refresh(delivery)

    refreshed_order = await order_service.get_order_for_admin(db, delivery.order_id)
    await notification_service.try_enqueue_order_status_notifications(
        db,
        order=refreshed_order,
        previous_status=previous_order_status,
        new_status=refreshed_order.status,
        source=source,
        delivery=delivery,
    )
    return delivery
