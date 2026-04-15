from typing import List

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from core.db import get_db
from core.models import User
from manage.schemas.order_schema import OrderCreate, OrderOut
from manage.services import order_service
from routers.user_router import get_current_user

router = APIRouter(prefix="/orders", tags=["Orders"])


@router.post("/", response_model=OrderOut, status_code=201)
async def create_order(
    payload: OrderCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await order_service.create_order(db, current_user.id, payload)


@router.get("/{order_id}", response_model=OrderOut, status_code=200)
async def get_order_by_id(
    order_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await order_service.get_order_by_id(db, current_user.id, order_id)


@router.get("/", response_model=List[OrderOut], status_code=200)
async def get_my_orders(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await order_service.get_customer_orders(db, current_user.id, limit=limit, offset=offset)
