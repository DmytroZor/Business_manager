from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from core.db import get_db
from core.models import UserRole
from manage.docs.api_docs import ERROR_RESPONSES, PRODUCT_DOCS
from manage.schemas.product_schema import (
    ActiveStatus,
    ProductCreate,
    ProductOut,
    ProductUpdate,
    SortField,
    SortOrder,
    StockStatus,
)
from manage.schemas.analytics_schema import ProductSalesAnalyticsOut, SalesAnalyticsPeriod, SalesAnalyticsSort
from manage.services import analytics_service, product_service
from routers.user_router import get_current_user

router = APIRouter(prefix="/products", tags=["Products"])


def _ensure_admin_role(current_user) -> None:
    if getattr(current_user, "role", None) != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Admin access required")


@router.get(
    "/{product_id}",
    response_model=ProductOut,
    status_code=200,
    summary=PRODUCT_DOCS["get_by_id"]["summary"],
    description=PRODUCT_DOCS["get_by_id"]["description"],
    responses={
        404: ERROR_RESPONSES["not_found"],
        422: ERROR_RESPONSES["validation"],
        500: ERROR_RESPONSES["internal"],
    },
)
async def get_product_by_id(product_id: int, db: AsyncSession = Depends(get_db)):
    product = await product_service.get_product_by_id(db, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return product


@router.get(
    "/",
    response_model=List[ProductOut],
    status_code=200,
    summary=PRODUCT_DOCS["list"]["summary"],
    description=PRODUCT_DOCS["list"]["description"],
    responses={
        422: ERROR_RESPONSES["validation"],
        500: ERROR_RESPONSES["internal"],
    },
)
async def get_all_products(
    sort_order: SortOrder = SortOrder.asc,
    limit: int = Query(default=10, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    sort_field: SortField = SortField.name,
    active_flag: ActiveStatus = ActiveStatus.active_products,
    stock_filter: StockStatus = StockStatus.all_products,
    search: str = Query(default=""),
    db: AsyncSession = Depends(get_db),
):
    products = await product_service.get_all_products(
        db,
        sort_field=sort_field,
        active_status=active_flag,
        sort_order=sort_order,
        offset=offset,
        limit=limit,
        search=search,
        stock_status=stock_filter,
    )
    return products


@router.post(
    "/",
    response_model=ProductOut,
    status_code=201,
    summary=PRODUCT_DOCS["create"]["summary"],
    description=PRODUCT_DOCS["create"]["description"],
    responses={
        401: ERROR_RESPONSES["unauthorized"],
        422: ERROR_RESPONSES["validation"],
        500: ERROR_RESPONSES["internal"],
    },
)
async def create_product(
    product: ProductCreate,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    return await product_service.create_product(db, product_data=product)


@router.put(
    "/{product_id}",
    response_model=ProductOut,
    summary=PRODUCT_DOCS["update"]["summary"],
    description=PRODUCT_DOCS["update"]["description"],
    responses={
        401: ERROR_RESPONSES["unauthorized"],
        404: ERROR_RESPONSES["not_found"],
        422: ERROR_RESPONSES["validation"],
        500: ERROR_RESPONSES["internal"],
    },
)
async def update_product(
    product_id: int,
    product: ProductUpdate,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    updated = await product_service.product_update_by_id(db, product_id, product)
    if not updated:
        raise HTTPException(status_code=404, detail="Product not found")
    return updated


@router.get(
    "/admin/sales-analytics",
    response_model=ProductSalesAnalyticsOut,
    status_code=200,
    summary="Admin: product sales analytics",
    description="Returns aggregated product sales for the selected period.",
)
async def get_admin_product_sales_analytics(
    period: SalesAnalyticsPeriod = SalesAnalyticsPeriod.month,
    sort_by: SalesAnalyticsSort = SalesAnalyticsSort.quantity,
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    _ensure_admin_role(current_user)
    result = await analytics_service.get_product_sales_analytics(
        db,
        period=period,
        sort_by=sort_by,
        limit=limit,
    )
    return ProductSalesAnalyticsOut(
        period=result.period,
        sort_by=result.sort_by,
        generated_at=result.generated_at,
        period_start=result.period_start,
        period_end=result.period_end,
        summary=result.summary,
        items=result.items,
    )
