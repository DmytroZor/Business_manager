from __future__ import annotations

from typing import Optional, Sequence

from fastapi import HTTPException, status
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core.models import Courier, Delivery, DeliveryStatus, Order, OrderStatus, UserRole
from manage.schemas.delivery_schema import DeliveryAssignCreate, DeliveryStatusUpdate


async def _get_order(db: AsyncSession, order_id: int) -> Order:
    stmt = (
        select(Order)
        .options(selectinload(Order.deliveries), selectinload(Order.items))
        .where(Order.id == order_id)
    )
    result = await db.execute(stmt)
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    return order


async def _get_courier_by_id(db: AsyncSession, courier_id: int) -> Courier:
    stmt = select(Courier).where(Courier.id == courier_id)
    result = await db.execute(stmt)
    courier = result.scalar_one_or_none()
    if not courier:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Courier not found")
    return courier


async def _get_delivery(db: AsyncSession, delivery_id: int) -> Delivery:
    stmt = (
        select(Delivery)
        .options(selectinload(Delivery.order), selectinload(Delivery.courier))
        .where(Delivery.id == delivery_id)
    )
    result = await db.execute(stmt)
    delivery = result.scalar_one_or_none()
    if not delivery:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Delivery not found")
    return delivery


async def assign_delivery(
    db: AsyncSession,
    order_id: int,
    payload: DeliveryAssignCreate,
) -> Delivery:
    order = await _get_order(db, order_id)
    courier = await _get_courier_by_id(db, payload.courier_id)

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

    delivery = Delivery(
        order_id=order.id,
        courier_id=courier.id,
        status=DeliveryStatus.ASSIGNED,
        scheduled_at=payload.scheduled_at,
        assigned_at=None,
        fee=payload.fee,
    )

    order.status = OrderStatus.PREPARING

    db.add(delivery)
    await db.commit()
    await db.refresh(delivery)
    return delivery


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
    delivery.picked_up_at = delivery.picked_up_at or delivery.assigned_at
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
    delivery.delivered_at = delivery.delivered_at or delivery.picked_up_at
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