from __future__ import annotations

from typing import Sequence

from fastapi import HTTPException, status
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core.models import DeliveryStatus, Order, OrderStatus, Product, Review
from manage.schemas.review_schema import CreateReview

#review_service

async def _get_order(db: AsyncSession, order_id: int) -> Order:
    stmt = (
        select(Order)
        .options(
            selectinload(Order.items),
            selectinload(Order.deliveries),
            selectinload(Order.reviews),
        )
        .where(Order.id == order_id)
    )
    result = await db.execute(stmt)
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    return order


async def create_review(
    db: AsyncSession,
    customer_id: int,
    order_id: int,
    payload: CreateReview,
) -> Review:
    order = await _get_order(db, order_id)

    if order.customer_id != customer_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your order")

    is_delivered = order.status == OrderStatus.DELIVERED or any(
        delivery.status == DeliveryStatus.DELIVERED for delivery in order.deliveries
    )
    if not is_delivered:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Review is allowed only after delivery is completed",
        )

    if payload.product_id is not None:
        product_ids_in_order = {item.product_id for item in order.items if item.product_id is not None}
        if payload.product_id not in product_ids_in_order:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Selected product does not belong to this order",
            )

    duplicate_stmt = select(Review).where(
        Review.order_id == order_id,
        Review.customer_id == customer_id,
        Review.product_id == payload.product_id,
    )
    duplicate_result = await db.execute(duplicate_stmt)
    if duplicate_result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Review for this order/product already exists",
        )

    review = Review(
        order_id=order_id,
        customer_id=customer_id,
        product_id=payload.product_id,
        rating=payload.rating,
        comment=payload.comment,
    )

    db.add(review)
    await db.commit()
    await db.refresh(review)
    return review


async def get_my_reviews(
    db: AsyncSession,
    customer_id: int,
    *,
    limit: int = 20,
    offset: int = 0,
) -> Sequence[Review]:
    stmt = (
        select(Review)
        .where(Review.customer_id == customer_id)
        .order_by(desc(Review.created_at))
        .limit(limit)
        .offset(offset)
    )
    result = await db.execute(stmt)
    return result.scalars().all()