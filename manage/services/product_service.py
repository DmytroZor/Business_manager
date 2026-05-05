from __future__ import annotations

from decimal import Decimal
from typing import Sequence

from fastapi import HTTPException, status
from sqlalchemy import and_, func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from additional import sku_generator
from core.models import Product
from manage.schemas.product_schema import (
    ActiveStatus,
    ProductCreate,
    ProductStockDocumentApply,
    ProductUpdate,
    SortField,
    SortOrder,
    StockStatus,
)
from manage.services import inventory_service


LOW_STOCK_THRESHOLD = Decimal("5.000")


def _base_product_query():
    return select(Product)


def _apply_active_filter(stmt, active_status: ActiveStatus):
    if active_status == ActiveStatus.active_products:
        return stmt.where(Product.is_active.is_(True))
    if active_status == ActiveStatus.inactive_products:
        return stmt.where(Product.is_active.is_(False))
    return stmt


def _apply_stock_filter(stmt, stock_status: StockStatus):
    if stock_status == StockStatus.in_stock:
        return stmt.where(Product.available_quantity > 0)
    if stock_status == StockStatus.low_stock:
        return stmt.where(and_(Product.available_quantity > 0, Product.available_quantity <= LOW_STOCK_THRESHOLD))
    if stock_status == StockStatus.out_of_stock:
        return stmt.where(Product.available_quantity <= 0)
    return stmt


def _apply_search(stmt, search: str | None):
    if not search:
        return stmt
    term = search.strip()
    if not term:
        return stmt
    like_term = f"%{term}%"
    return stmt.where(
        Product.name.ilike(like_term)
        | Product.sku.ilike(like_term)
        | Product.description.ilike(like_term)
    )


async def create_product(db: AsyncSession, product_data: ProductCreate):
    product = Product(
        name=product_data.name,
        description=product_data.description,
        image_url=product_data.image_url,
        base_unit_price=product_data.base_unit_price,
        last_purchase_price=None,
        unit=product_data.unit,
        available_quantity=product_data.available_quantity,
        reserved_quantity=Decimal("0.000"),
        is_active=product_data.is_active,
        sku=sku_generator.generate_sku(name=product_data.name, unit=product_data.unit),
    )
    db.add(product)
    try:
        await db.flush()
        await inventory_service.ensure_opening_batch_for_product(db, product)
        await db.commit()
        await db.refresh(product)
        return product
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Product with this SKU already exists") from exc
    except SQLAlchemyError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database error while creating product",
        ) from exc


async def get_product_by_id(db: AsyncSession, product_id: int):
    q = await db.execute(select(Product).where(Product.id == product_id))
    return q.scalar_one_or_none()


async def product_update_by_id(db: AsyncSession, product_id: int, product_data: ProductUpdate):
    product = await get_product_by_id(db, product_id)
    if not product:
        return None

    update_data = product_data.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No valid fields provided for update")

    for field, value in update_data.items():
        setattr(product, field, value)

    try:
        await db.flush()
        await inventory_service.ensure_opening_batch_for_product(db, product)
        await db.commit()
        await db.refresh(product)
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Product update violates a unique constraint",
        ) from exc
    except SQLAlchemyError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database error while updating product",
        ) from exc

    return product


async def product_delete_by_id(db: AsyncSession, product_id: int):
    product = await get_product_by_id(db, product_id)
    if not product:
        return False
    await db.delete(product)
    try:
        await db.commit()
        return True
    except SQLAlchemyError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database error while deleting product",
        ) from exc


async def apply_stock_document(
    db: AsyncSession,
    payload: ProductStockDocumentApply,
    *,
    actor_user_id: int | None = None,
):
    return await inventory_service.apply_stock_document(db, payload, actor_user_id=actor_user_id)


async def list_recent_stock_documents(db: AsyncSession, *, limit: int = 10):
    return await inventory_service.list_recent_stock_documents(db, limit=limit)


async def get_product_batches(db: AsyncSession, product_id: int, *, limit: int = 20):
    return await inventory_service.get_product_batches(db, product_id, limit=limit)


async def get_all_products(
    db: AsyncSession,
    sort_field: SortField,
    active_status: ActiveStatus,
    sort_order: SortOrder,
    offset: int = 0,
    limit: int = 10,
    *,
    search: str | None = None,
    stock_status: StockStatus = StockStatus.all_products,
) -> Sequence[Product]:
    stmt = _base_product_query()
    stmt = _apply_active_filter(stmt, active_status)
    stmt = _apply_stock_filter(stmt, stock_status)
    stmt = _apply_search(stmt, search)

    sort_col = getattr(Product, sort_field.value)
    if sort_order == SortOrder.desc:
        stmt = stmt.order_by(sort_col.desc(), Product.id.desc())
    else:
        stmt = stmt.order_by(sort_col.asc(), Product.id.asc())

    stmt = stmt.offset(offset).limit(limit)
    result = await db.execute(stmt)
    return result.scalars().all()
