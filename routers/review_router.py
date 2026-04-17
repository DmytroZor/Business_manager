from typing import List

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from core.db import get_db
from core.models import User, UserRole
from manage.schemas.review_schema import CreateReview, ReviewOut
from manage.services import review_service
from routers.user_router import get_current_user

router = APIRouter(prefix="/reviews", tags=["Reviews"])


def _get_customer_profile_id(current_user: User) -> int:
    if current_user.customer_profile is None:
        raise ValueError("Customer profile is missing")
    return current_user.customer_profile.id


@router.post(
    "/orders/{order_id}",
    response_model=ReviewOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create review for delivered order",
    description="Customer leaves a review after the order has been delivered.",
)
async def create_order_review(
    order_id: int,
    payload: CreateReview,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != UserRole.CUSTOMER:
        from fastapi import HTTPException
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only customers can leave reviews")

    customer_id = _get_customer_profile_id(current_user)
    return await review_service.create_review(db, customer_id, order_id, payload)


@router.get(
    "/my",
    response_model=List[ReviewOut],
    status_code=status.HTTP_200_OK,
    summary="List my reviews",
    description="Returns reviews created by the authenticated customer.",
)
async def get_my_reviews(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != UserRole.CUSTOMER:
        from fastapi import HTTPException
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only customers can access their reviews")

    customer_id = _get_customer_profile_id(current_user)
    return await review_service.get_my_reviews(db, customer_id, limit=limit, offset=offset)