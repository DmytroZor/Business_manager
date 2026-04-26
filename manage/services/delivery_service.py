from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Sequence

from fastapi import HTTPException, status
from sqlalchemy import desc, exists, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core.models import Courier, Delivery, DeliveryStatus, Order, OrderStatus, UserRole
from manage.schemas.delivery_schema import DeliveryAssignCreate, DeliverySelfAssignCreate, DeliveryStatusUpdate


async def _get_order(db: AsyncSession, order_id: int) -> Order:
    stmt = (
        select(Order)
        .options(
            selectinload(Order.deliveries),
            selectinload(Order.items),
        )
        .where(Order.id == order_id)
    )
    result = await db.execute(stmt)
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Courier not found")
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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Courier profile not found")
    return courier


async def _get_delivery(db: AsyncSession, delivery_id: int) -> Delivery:
    stmt = (
        select(Delivery)
        .options(
            selectinload(Delivery.order),
            selectinload(Delivery.courier),
        )
        .where(Delivery.id == delivery_id)
    )
    result = await db.execute(stmt)
    delivery = result.scalar_one_or_none()
    if not delivery:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Delivery not found")
    return delivery


def _validate_courier_for_assignment(courier: Courier) -> None:
    if courier.user.role != UserRole.COURIER:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Selected user is not a courier",
        )

    if not courier.user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Courier account is inactive",
        )


def _validate_order_status(order: Order) -> None:
    if order.status not in {OrderStatus.PLACED, OrderStatus.PREPARING}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Order is not in a state that allows delivery assignment",
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
            detail="Order already has an active delivery",
        )


async def _create_assigned_delivery(
    db: AsyncSession,
    *,
    order: Order,
    courier: Courier,
    scheduled_at: datetime | None,
    fee,
) -> Delivery:
    _validate_courier_for_assignment(courier)
    _validate_order_status(order)
    await _ensure_no_active_delivery(db, order.id)

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
    await db.commit()
    await db.refresh(delivery)
    return delivery


async def assign_delivery(
    db: AsyncSession,
    order_id: int,
    payload: DeliveryAssignCreate,
) -> Delivery:
    order = await _get_order(db, order_id)
    courier = await _get_courier_by_id(db, payload.courier_id)
    return await _create_assigned_delivery(
        db,
        order=order,
        courier=courier,
        scheduled_at=payload.scheduled_at,
        fee=payload.fee,
    )


async def get_available_orders_for_courier(
    db: AsyncSession,
    *,
    limit: int = 20,
    offset: int = 0,
) -> Sequence[Order]:
    active_delivery_exists = exists().where(
        Delivery.order_id == Order.id,
        Delivery.status.in_(
            [DeliveryStatus.ASSIGNED, DeliveryStatus.PENDING, DeliveryStatus.PICKED_UP]
        ),
    )
    stmt = (
        select(Order)
        .options(selectinload(Order.items))
        .where(Order.status.in_([OrderStatus.PLACED, OrderStatus.PREPARING]))
        .where(~active_delivery_exists)
        .order_by(desc(Order.placed_at))
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
        .options(selectinload(Delivery.order))
        .where(Delivery.courier_id == courier_id)
        .order_by(desc(Delivery.created_at))
        .limit(limit)
        .offset(offset)
    )
    if status_filter is not None:
        stmt = stmt.where(Delivery.status == status_filter)

    result = await db.execute(stmt)
    return result.scalars().all()


async def pick_up_delivery(db: AsyncSession, delivery_id: int, courier_id: int) -> Delivery:
    delivery = await _get_delivery(db, delivery_id)

    if delivery.courier_id != courier_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your delivery")

    if delivery.status not in {DeliveryStatus.ASSIGNED, DeliveryStatus.PENDING}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Delivery cannot be picked up in its current status",
        )

    delivery.status = DeliveryStatus.PICKED_UP
    delivery.picked_up_at = datetime.now(timezone.utc)
    delivery.order.status = OrderStatus.OUT_FOR_DELIVERY

    await db.commit()
    await db.refresh(delivery)
    return delivery


async def complete_delivery(db: AsyncSession, delivery_id: int, courier_id: int) -> Delivery:
    delivery = await _get_delivery(db, delivery_id)

    if delivery.courier_id != courier_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your delivery")

    if delivery.status != DeliveryStatus.PICKED_UP:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only picked-up deliveries can be completed",
        )

    delivery.status = DeliveryStatus.DELIVERED
    delivery.delivered_at = datetime.now(timezone.utc)
    delivery.order.status = OrderStatus.DELIVERED

    await db.commit()
    await db.refresh(delivery)
    return delivery


async def fail_delivery(
    db: AsyncSession,
    delivery_id: int,
    courier_id: int,
    payload: DeliveryStatusUpdate,
) -> Delivery:
    delivery = await _get_delivery(db, delivery_id)

    if delivery.courier_id != courier_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your delivery")

    if delivery.status not in {DeliveryStatus.ASSIGNED, DeliveryStatus.PICKED_UP}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Delivery cannot be failed in its current status",
        )

    if not payload.failed_reason:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="failed_reason is required when marking delivery as failed",
        )

    delivery.status = DeliveryStatus.FAILED
    delivery.failed_reason = payload.failed_reason
    delivery.order.status = OrderStatus.PREPARING

    await db.commit()
    await db.refresh(delivery)
    return delivery
