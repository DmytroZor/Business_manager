from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from core.models import Courier
from core.db import get_db
from core.models import User, UserRole, DeliveryStatus
from manage.schemas.delivery_schema import (
    DeliveryAssignCreate,
    DeliveryOut,
    DeliveryStatusUpdate,
)
from manage.services import delivery_service
from routers.user_router import get_current_user

router = APIRouter(prefix="/deliveries", tags=["Deliveries"])


def _ensure_role(current_user: User, *allowed_roles: UserRole) -> None:
    if current_user.role not in allowed_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions",
        )


async def _get_courier_profile_id(db: AsyncSession, current_user: User) -> int:
    stmt = select(Courier.id).where(Courier.user_id == current_user.id)
    result = await db.execute(stmt)
    courier_id = result.scalar_one_or_none()

    if courier_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Courier profile is missing for this user",
        )

    return courier_id


def _get_customer_profile_id(current_user: User) -> int:
    if current_user.customer_profile is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Customer profile is missing for this user",
        )
    return current_user.customer_profile.id


@router.post(
    "/orders/{order_id}",
    response_model=DeliveryOut,
    status_code=status.HTTP_201_CREATED,
    summary="Assign courier delivery to order",
    description="Creates a delivery record for an order and assigns a courier profile.",
)
async def assign_delivery_to_order(
        order_id: int,
        payload: DeliveryAssignCreate,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_user),
):
    _ensure_role(current_user, UserRole.ADMIN)
    return await delivery_service.assign_delivery(db, order_id, payload)


@router.get(
    "/my",
    response_model=List[DeliveryOut],
    status_code=status.HTTP_200_OK,
    summary="List current courier deliveries",
    description="Returns deliveries assigned to the authenticated courier.",
)
async def get_my_deliveries(
        status_filter: Optional[DeliveryStatus] = Query(default=None),
        limit: int = Query(default=20, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_user),
):
    _ensure_role(current_user, UserRole.COURIER)
    courier_id = await _get_courier_profile_id(db, current_user)
    return await delivery_service.get_my_deliveries(
        db,
        courier_id,
        status_filter=status_filter,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{delivery_id}",
    response_model=DeliveryOut,
    status_code=status.HTTP_200_OK,
    summary="Get delivery by ID",
    description="Courier can read own delivery, admin can read any delivery.",
)
async def get_delivery_by_id(
        delivery_id: int,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_user),
):
    delivery = await delivery_service.get_delivery_by_id(db, delivery_id)

    if current_user.role == UserRole.ADMIN:
        return delivery

    if current_user.role != UserRole.COURIER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

    courier_id = await _get_courier_profile_id(db, current_user)
    if delivery.courier_id != courier_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your delivery")

    return delivery


@router.patch(
    "/{delivery_id}/pick-up",
    response_model=DeliveryOut,
    status_code=status.HTTP_200_OK,
    summary="Mark delivery as picked up",
    description="Courier marks delivery as picked up from the shop.",
)
async def pick_up_delivery(
        delivery_id: int,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_user),
):
    _ensure_role(current_user, UserRole.COURIER)
    courier_id = await _get_courier_profile_id(db, current_user)
    return await delivery_service.pick_up_delivery(db, delivery_id, courier_id)


@router.patch(
    "/{delivery_id}/complete",
    response_model=DeliveryOut,
    status_code=status.HTTP_200_OK,
    summary="Mark delivery as completed",
    description="Courier marks delivery as successfully delivered.",
)
async def complete_delivery(
        delivery_id: int,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_user),
):
    _ensure_role(current_user, UserRole.COURIER)
    courier_id = await _get_courier_profile_id(db, current_user)
    return await delivery_service.complete_delivery(db, delivery_id, courier_id)


@router.patch(
    "/{delivery_id}/fail",
    response_model=DeliveryOut,
    status_code=status.HTTP_200_OK,
    summary="Mark delivery as failed",
    description="Courier reports a failed delivery attempt.",
)
async def fail_delivery(
        delivery_id: int,
        payload: DeliveryStatusUpdate,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_user),
):
    _ensure_role(current_user, UserRole.COURIER)
    courier_id = await _get_courier_profile_id(db, current_user)
    return await delivery_service.fail_delivery(db, delivery_id, courier_id, payload)
