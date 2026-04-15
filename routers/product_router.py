from sqlalchemy.ext.asyncio import AsyncSession
from core.db import get_db
from fastapi import APIRouter, Depends, HTTPException, Query
from manage.docs.api_docs import PRODUCT_DOCS, ERROR_RESPONSES
from manage.schemas.product_schema import ProductOut, ProductCreate, ProductUpdate, SortField, SortOrder, ActiveStatus
from manage.services import product_service
from typing import List
from routers.user_router import get_current_user

router = APIRouter(prefix="/products", tags=["Products"])


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
async def get_all_products(sort_order: SortOrder = SortOrder.asc,
                           limit: int = Query(default=10, ge=1, le=100),
                           offset: int = Query(default=0, ge=0),
                           sort_field: SortField = SortField.name,
                           active_flag: ActiveStatus = ActiveStatus.active_products,
                           db: AsyncSession = Depends(get_db)):
    products = await product_service.get_all_products(db, sort_field=sort_field,
                                                      active_status=active_flag,
                                                      sort_order=sort_order,
                                                      offset=offset,
                                                      limit=limit)
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
async def create_product(product: ProductCreate, db: AsyncSession = Depends(get_db), _=Depends(get_current_user)):
    created = await product_service.create_product(db, product_data=product)
    return created


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
async def update_product(product_id: int, product: ProductUpdate, db: AsyncSession = Depends(get_db), _=Depends(get_current_user)):
    update = await product_service.product_update_by_id(db, product_id, product)
    if not update:
        raise HTTPException(status_code=404, detail="Product not found")
    return update
