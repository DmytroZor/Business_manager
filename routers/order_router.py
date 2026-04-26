from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from core.db import get_db
from core.models import OrderStatus, User, UserRole
from manage.docs.api_docs import ORDER_DOCS, ERROR_RESPONSES
from manage.schemas.order_schema import (
    AdminOrderOut,
    AdminPhoneOrderCreate,
    OrderCancelPayload,
    OrderCreate,
    OrderOut,
)
from manage.services import order_service
from routers.user_router import get_current_user

router = APIRouter(prefix="/orders", tags=["Orders"])


def _ensure_admin(current_user: User) -> None:
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")


@router.post(
    "/",
    response_model=OrderOut,
    status_code=201,
    summary=ORDER_DOCS["create"]["summary"],
    description=ORDER_DOCS["create"]["description"],
    responses={
        400: ERROR_RESPONSES["bad_request"],
        401: ERROR_RESPONSES["unauthorized"],
        404: ERROR_RESPONSES["not_found"],
        422: ERROR_RESPONSES["validation"],
        500: ERROR_RESPONSES["internal"],
    },
)
async def create_order(
    payload: OrderCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await order_service.create_order(db, current_user.id, payload)


@router.get(
    "/{order_id}",
    response_model=OrderOut,
    status_code=200,
    summary=ORDER_DOCS["get_by_id"]["summary"],
    description=ORDER_DOCS["get_by_id"]["description"],
    responses={
        401: ERROR_RESPONSES["unauthorized"],
        404: ERROR_RESPONSES["not_found"],
        500: ERROR_RESPONSES["internal"],
    },
)
async def get_order_by_id(
    order_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await order_service.get_order_by_id(db, current_user.id, order_id)


@router.get(
    "/",
    response_model=List[OrderOut],
    status_code=200,
    summary=ORDER_DOCS["list"]["summary"],
    description=ORDER_DOCS["list"]["description"],
    responses={
        401: ERROR_RESPONSES["unauthorized"],
        422: ERROR_RESPONSES["validation"],
        500: ERROR_RESPONSES["internal"],
    },
)
async def get_my_orders(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await order_service.get_customer_orders(db, current_user.id, limit=limit, offset=offset)


@router.get(
    "/admin/orders",
    response_model=List[AdminOrderOut],
    status_code=200,
    summary="Admin: list orders",
    description="Returns recent orders with customer, address, and courier context for admin workflows.",
)
async def admin_get_orders(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    status_filter: OrderStatus | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ensure_admin(current_user)
    orders = await order_service.get_orders_for_admin(
        db,
        limit=limit,
        offset=offset,
        status_filter=status_filter,
    )
    return [AdminOrderOut.model_validate(order_service.build_admin_order_payload(order)) for order in orders]


@router.get(
    "/admin/orders/{order_id}",
    response_model=AdminOrderOut,
    status_code=200,
    summary="Admin: get order details",
    description="Returns a single order with customer, address, courier, and item context.",
)
async def admin_get_order_by_id(
    order_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ensure_admin(current_user)
    order = await order_service.get_order_for_admin(db, order_id)
    return AdminOrderOut.model_validate(order_service.build_admin_order_payload(order))


@router.post(
    "/admin/phone-order",
    response_model=AdminOrderOut,
    status_code=201,
    summary="Admin: create phone order",
    description="Admin creates an order for a customer who called by phone.",
)
async def admin_create_phone_order(
    payload: AdminPhoneOrderCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ensure_admin(current_user)
    order = await order_service.create_phone_order_by_admin(db, payload)
    return AdminOrderOut.model_validate(order_service.build_admin_order_payload(order))


@router.patch(
    "/admin/orders/{order_id}/cancel",
    response_model=AdminOrderOut,
    status_code=200,
    summary="Admin: cancel order",
    description="Admin cancels an order before it is out for delivery.",
)
async def admin_cancel_order(
    order_id: int,
    payload: OrderCancelPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ensure_admin(current_user)
    order = await order_service.cancel_order_by_admin(db, order_id, payload)
    return AdminOrderOut.model_validate(order_service.build_admin_order_payload(order))
