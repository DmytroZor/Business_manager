from typing import List

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from core.db import get_db
from core.models import User
from manage.docs.api_docs import ORDER_DOCS, ERROR_RESPONSES
from manage.schemas.order_schema import OrderCreate, OrderOut
from manage.services import order_service
from routers.user_router import get_current_user

router = APIRouter(prefix="/orders", tags=["Orders"])


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
