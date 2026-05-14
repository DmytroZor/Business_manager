from __future__ import annotations

import logging
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
logger = logging.getLogger("bms.product")
PRODUCT_CATEGORY_FILTERS: dict[str, tuple[str, ...]] = {
    "fish": (
        "сібас",
        "дорадо",
        "лосос",
        "форел",
        "скумбр",
        "оселед",
        "тунец",
        "тунець",
        "палтус",
        "тріск",
        "треск",
        "хек",
        "минтай",
        "камбал",
        "сардин",
        "ставрид",
        "кефаль",
        "корюш",
        "барабуль",
        "окун",
        "сом",
        "щук",
        "судак",
        "sea bass",
        "salmon",
        "trout",
        "mackerel",
        "tuna",
        "cod",
        "halibut",
        "herring",
    ),
    "seafood": (
        "кревет",
        "міді",
        "мидии",
        "кальмар",
        "восьмин",
        "гребінец",
        "гребенец",
        "устриц",
        "краб",
        "лангуст",
        "рак",
        "ікра",
        "икра",
        "морепродукт",
        "рапан",
        "shrimp",
        "mussel",
        "squid",
        "octopus",
        "oyster",
        "crab",
        "seafood",
        "scallop",
    ),
    "frozen": (
        "морож",
        "заморож",
        "frozen",
        "half shell",
        "кільця",
        "rings",
        "очищен",
        "cleaned",
        "котлет",
        "фарш",
        "коктейл",
        "cocktail",
        "стейк",
        "steak",
        "філе",
        "филе",
    ),
}


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


def _apply_category_filter(stmt, category_filter: str | None):
    if not category_filter or category_filter == "all":
        return stmt

    keywords = PRODUCT_CATEGORY_FILTERS.get(category_filter)
    if not keywords:
        return stmt

    category_conditions = []
    for keyword in keywords:
        like_term = f"%{keyword}%"
        category_conditions.append(Product.name.ilike(like_term) | Product.description.ilike(like_term))

    if not category_conditions:
        return stmt

    condition = category_conditions[0]
    for extra_condition in category_conditions[1:]:
        condition = condition | extra_condition
    return stmt.where(condition)


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
        logger.exception("Product creation failed because of SKU conflict for name=%s unit=%s", product_data.name, product_data.unit)
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Product with this SKU already exists") from exc
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.exception("Database error while creating product name=%s unit=%s", product_data.name, product_data.unit)
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
        logger.exception("Product update violates unique constraint for product_id=%s", product_id)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Product update violates a unique constraint",
        ) from exc
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.exception("Database error while updating product_id=%s", product_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database error while updating product",
        ) from exc

    return product


async def product_delete_by_id(
    db: AsyncSession,
    product_id: int,
    *,
    reason: str,
    actor_user_id: int | None = None,
):
    product = await get_product_by_id(db, product_id)
    if not product:
        return False

    clean_reason = reason.strip()
    if not clean_reason:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Deletion reason is required")

    reserved_quantity = Decimal(str(product.reserved_quantity or 0))
    if reserved_quantity > 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete a product that still has reserved quantity",
        )

    logger.warning(
        "Deleting product id=%s sku=%s name=%s actor_user_id=%s reason=%s",
        product.id,
        product.sku,
        product.name,
        actor_user_id,
        clean_reason,
    )
    await db.delete(product)
    try:
        await db.commit()
        return True
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.exception("Database error while deleting product_id=%s", product_id)
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


async def list_recent_stock_documents(
    db: AsyncSession,
    *,
    limit: int = 10,
    days_back: int | None = None,
):
    return await inventory_service.list_recent_stock_documents(db, limit=limit, days_back=days_back)


async def get_stock_document_by_id(db: AsyncSession, document_id: int):
    return await inventory_service.get_stock_document_by_id(db, document_id)


async def get_next_receipt_document_number(db: AsyncSession, *, document_date):
    return await inventory_service.get_next_receipt_document_number(db, document_date=document_date)


async def get_product_batches(db: AsyncSession, product_id: int, *, limit: int = 20):
    return await inventory_service.get_product_batches(db, product_id, limit=limit)


async def list_products_for_reference(
    db: AsyncSession,
    *,
    include_inactive: bool = True,
    limit: int = 500,
) -> Sequence[Product]:
    stmt = select(Product).order_by(Product.is_active.desc(), Product.name.asc(), Product.id.asc()).limit(limit)
    if not include_inactive:
        stmt = stmt.where(Product.is_active.is_(True))
    result = await db.execute(stmt)
    return result.scalars().all()


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
    category_filter: str | None = None,
) -> Sequence[Product]:
    stmt = _base_product_query()
    stmt = _apply_active_filter(stmt, active_status)
    stmt = _apply_stock_filter(stmt, stock_status)
    stmt = _apply_search(stmt, search)
    stmt = _apply_category_filter(stmt, category_filter)

    sort_col = getattr(Product, sort_field.value)
    if sort_order == SortOrder.desc:
        stmt = stmt.order_by(sort_col.desc(), Product.id.desc())
    else:
        stmt = stmt.order_by(sort_col.asc(), Product.id.asc())

    stmt = stmt.offset(offset).limit(limit)
    result = await db.execute(stmt)
    return result.scalars().all()


async def count_products(
    db: AsyncSession,
    *,
    active_status: ActiveStatus,
    search: str | None = None,
    stock_status: StockStatus = StockStatus.all_products,
    category_filter: str | None = None,
) -> int:
    stmt = select(func.count(Product.id))
    stmt = _apply_active_filter(stmt, active_status)
    stmt = _apply_stock_filter(stmt, stock_status)
    stmt = _apply_search(stmt, search)
    stmt = _apply_category_filter(stmt, category_filter)
    result = await db.execute(stmt)
    return int(result.scalar_one() or 0)
