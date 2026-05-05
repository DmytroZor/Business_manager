from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_DOWN
from typing import Sequence

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from additional import sku_generator
from core.models import (
    Order,
    OrderItem,
    OrderItemBatchAllocation,
    Product,
    ProductBatch,
    StockDocument,
    StockDocumentItem,
    StockDocumentType,
    Supplier,
)
from manage.schemas.product_schema import ProductStockDocumentApply, ProductStockDocumentRow


LEGACY_BATCH_CODE = "opening-balance"
LOW_STOCK_THRESHOLD = Decimal("5.000")


@dataclass(slots=True)
class ProductStockDocumentResult:
    document: StockDocument
    created_count: int
    updated_count: int
    touched_products: list[Product]


def quantize_money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_DOWN)


def quantize_quantity(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.001"), rounding=ROUND_DOWN)


def normalize_text(value: str | None) -> str:
    return (value or "").strip().casefold()


def product_stock_on_hand(product: Product) -> Decimal:
    return quantize_quantity(
        Decimal(str(product.available_quantity or 0)) + Decimal(str(product.reserved_quantity or 0))
    )


def reserve_product_quantity(product: Product, quantity: Decimal) -> None:
    current_available = Decimal(str(product.available_quantity or 0))
    current_reserved = Decimal(str(product.reserved_quantity or 0))
    if current_available < quantity:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"РќРµРґРѕСЃС‚Р°С‚РЅСЊРѕ РІС–Р»СЊРЅРѕРіРѕ Р·Р°Р»РёС€РєСѓ РґР»СЏ С‚РѕРІР°СЂСѓ В«{product.name}В».",
        )
    product.available_quantity = quantize_quantity(current_available - quantity)
    product.reserved_quantity = quantize_quantity(current_reserved + quantity)


def release_reserved_quantity(product: Product, quantity: Decimal) -> None:
    current_available = Decimal(str(product.available_quantity or 0))
    current_reserved = Decimal(str(product.reserved_quantity or 0))
    if current_reserved < quantity:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"РќРµ РІРґР°Р»РѕСЃСЏ РїРѕРІРµСЂРЅСѓС‚Рё СЂРµР·РµСЂРІ РґР»СЏ С‚РѕРІР°СЂСѓ В«{product.name}В»: РєС–Р»СЊРєС–СЃС‚СЊ Сѓ СЂРµР·РµСЂРІС– РЅРµ Р·Р±С–РіР°С”С‚СЊСЃСЏ.",
        )
    product.available_quantity = quantize_quantity(current_available + quantity)
    product.reserved_quantity = quantize_quantity(current_reserved - quantity)


def consume_reserved_quantity(product: Product, quantity: Decimal) -> None:
    current_reserved = Decimal(str(product.reserved_quantity or 0))
    if current_reserved < quantity:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"РќРµ РІРґР°Р»РѕСЃСЏ СЃРїРёСЃР°С‚Рё СЂРµР·РµСЂРІ РґР»СЏ С‚РѕРІР°СЂСѓ В«{product.name}В»: РєС–Р»СЊРєС–СЃС‚СЊ Сѓ СЂРµР·РµСЂРІС– РЅРµ Р·Р±С–РіР°С”С‚СЊСЃСЏ.",
        )
    product.reserved_quantity = quantize_quantity(current_reserved - quantity)


def restore_picked_up_quantity(product: Product, quantity: Decimal) -> None:
    current_reserved = Decimal(str(product.reserved_quantity or 0))
    product.reserved_quantity = quantize_quantity(current_reserved + quantity)


def build_document_number(document_type: StockDocumentType) -> str:
    prefix_map = {
        StockDocumentType.RECEIPT: "REC",
        StockDocumentType.ADJUSTMENT: "ADJ",
        StockDocumentType.INVENTORY_COUNT: "INV",
    }
    prefix = prefix_map.get(document_type, "DOC")
    return f"{prefix}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"


async def _get_supplier_for_update(db: AsyncSession, supplier_name: str) -> Supplier | None:
    result = await db.execute(
        select(Supplier)
        .where(func.lower(Supplier.name) == supplier_name.casefold())
        .with_for_update()
    )
    return result.scalars().first()


async def _get_or_create_supplier(
    db: AsyncSession,
    *,
    name: str | None,
    phone: str | None,
    email: str | None,
    notes: str | None,
) -> Supplier | None:
    clean_name = (name or "").strip()
    if not clean_name:
        return None

    supplier = await _get_supplier_for_update(db, clean_name)
    if supplier is not None:
        if phone:
            supplier.phone = phone
        if email:
            supplier.email = email
        if notes:
            supplier.notes = notes
        return supplier

    supplier = Supplier(name=clean_name, phone=phone, email=email, notes=notes)
    db.add(supplier)
    await db.flush()
    return supplier


async def get_product_by_name_and_unit_for_update(
    db: AsyncSession,
    *,
    name: str,
    unit: str,
) -> Product | None:
    stmt = (
        select(Product)
        .where(func.lower(Product.name) == name.casefold())
        .where(func.lower(Product.unit) == unit.casefold())
        .order_by(Product.is_active.desc(), Product.updated_at.desc(), Product.id.desc())
        .with_for_update()
    )
    result = await db.execute(stmt)
    return result.scalars().first()


async def get_products_for_update(db: AsyncSession, product_ids: Sequence[int]) -> dict[int, Product]:
    ordered_ids = sorted(set(product_ids))
    if not ordered_ids:
        return {}

    result = await db.execute(
        select(Product)
        .where(Product.id.in_(ordered_ids))
        .order_by(Product.id.asc())
        .with_for_update()
    )
    return {product.id: product for product in result.scalars().all()}


async def _create_product_from_document_row(row: ProductStockDocumentRow) -> Product:
    sale_price = row.sale_unit_price or row.purchase_unit_price
    if sale_price is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Р”Р»СЏ РЅРѕРІРѕРіРѕ С‚РѕРІР°СЂСѓ В«{row.name}В» РїРѕС‚СЂС–Р±РЅРѕ РІРєР°Р·Р°С‚Рё С†С–РЅСѓ РїСЂРѕРґР°Р¶Сѓ Р°Р±Рѕ Р·Р°РєСѓРїС–РІР»С–.",
        )

    quantity_value = quantize_quantity(row.quantity_value)
    if quantity_value < 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"РќРµ РјРѕР¶РЅР° Р·РјРµРЅС€РёС‚Рё Р·Р°Р»РёС€РѕРє РґР»СЏ С‚РѕРІР°СЂСѓ В«{row.name}В», СЏРєРѕРіРѕ С‰Рµ РЅРµРјР°С” РІ Р±Р°Р·С–.",
        )

    product = Product(
        name=row.name,
        description=None,
        image_url=None,
        base_unit_price=quantize_money(sale_price),
        last_purchase_price=quantize_money(row.purchase_unit_price) if row.purchase_unit_price is not None else None,
        unit=row.unit,
        available_quantity=Decimal("0.000"),
        reserved_quantity=Decimal("0.000"),
        is_active=True,
        sku=sku_generator.generate_sku(name=row.name, unit=row.unit),
    )
    return product


async def ensure_opening_batch_for_product(db: AsyncSession, product: Product) -> None:
    current_total = product_stock_on_hand(product)
    if current_total <= 0:
        return

    batches = await _load_batches_for_update(db, product_id=product.id, include_empty=True)
    batch_total = quantize_quantity(
        sum((Decimal(str(batch.available_quantity or 0)) for batch in batches), Decimal("0.000"))
    )
    missing_quantity = quantize_quantity(current_total - batch_total)
    if missing_quantity <= 0:
        return

    opening_batch = next(
        (
            batch
            for batch in batches
            if normalize_text(batch.batch_code) == LEGACY_BATCH_CODE
            and not batch.serial_code
            and batch.expires_at is None
        ),
        None,
    )

    if opening_batch is None:
        opening_batch = ProductBatch(
            product_id=product.id,
            batch_code=LEGACY_BATCH_CODE,
            purchase_unit_price=product.last_purchase_price or product.base_unit_price,
            original_quantity=missing_quantity,
            available_quantity=missing_quantity,
            note="РђРІС‚РѕРјР°С‚РёС‡РЅРѕ СЃС‚РІРѕСЂРµРЅРёР№ РїРѕС‡Р°С‚РєРѕРІРёР№ РїР°СЂС‚С–Р№РЅРёР№ Р·Р°Р»РёС€РѕРє.",
        )
        db.add(opening_batch)
        await db.flush()
        return

    opening_batch.original_quantity = quantize_quantity(
        Decimal(str(opening_batch.original_quantity or 0)) + missing_quantity
    )
    opening_batch.available_quantity = quantize_quantity(
        Decimal(str(opening_batch.available_quantity or 0)) + missing_quantity
    )


async def _load_batches_for_update(
    db: AsyncSession,
    *,
    product_id: int,
    include_empty: bool = False,
) -> list[ProductBatch]:
    stmt = (
        select(ProductBatch)
        .where(ProductBatch.product_id == product_id)
        .order_by(
            ProductBatch.expires_at.is_(None),
            ProductBatch.expires_at.asc(),
            ProductBatch.received_at.asc(),
            ProductBatch.id.asc(),
        )
        .with_for_update()
    )
    if not include_empty:
        stmt = stmt.where(ProductBatch.available_quantity > 0)
    result = await db.execute(stmt)
    return result.scalars().all()


def _batch_matches_row(batch: ProductBatch, row: ProductStockDocumentRow, supplier_id: int | None) -> bool:
    return (
        normalize_text(batch.batch_code) == normalize_text(row.batch_code)
        and normalize_text(batch.serial_code) == normalize_text(row.serial_code)
        and batch.expires_at == row.expires_at
        and batch.supplier_id == supplier_id
        and (
            (batch.purchase_unit_price is None and row.purchase_unit_price is None)
            or (
                batch.purchase_unit_price is not None
                and row.purchase_unit_price is not None
                and quantize_money(Decimal(str(batch.purchase_unit_price))) == quantize_money(row.purchase_unit_price)
            )
        )
    )


async def _find_or_create_batch_for_increase(
    db: AsyncSession,
    *,
    product: Product,
    supplier: Supplier | None,
    document: StockDocument,
    document_item: StockDocumentItem,
    row: ProductStockDocumentRow,
) -> ProductBatch:
    batches = await _load_batches_for_update(db, product_id=product.id, include_empty=True)
    supplier_id = supplier.id if supplier is not None else None
    for batch in batches:
        if _batch_matches_row(batch, row, supplier_id):
            return batch

    batch = ProductBatch(
        product_id=product.id,
        supplier_id=supplier_id,
        stock_document_id=document.id,
        stock_document_item_id=document_item.id,
        batch_code=row.batch_code,
        serial_code=row.serial_code,
        expires_at=row.expires_at,
        purchase_unit_price=quantize_money(row.purchase_unit_price) if row.purchase_unit_price is not None else None,
        original_quantity=Decimal("0.000"),
        available_quantity=Decimal("0.000"),
        note=row.note,
    )
    db.add(batch)
    await db.flush()
    return batch


async def _decrease_batches(
    db: AsyncSession,
    *,
    product: Product,
    row: ProductStockDocumentRow,
    quantity_to_remove: Decimal,
) -> None:
    await ensure_opening_batch_for_product(db, product)

    batches = await _load_batches_for_update(db, product_id=product.id, include_empty=False)
    if row.batch_code or row.serial_code or row.expires_at:
        supplier_id = None
        batches = [batch for batch in batches if _batch_matches_row(batch, row, supplier_id)]
        if not batches:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Р”Р»СЏ С‚РѕРІР°СЂСѓ В«{product.name}В» РЅРµ Р·РЅР°Р№РґРµРЅРѕ РїР°СЂС‚С–СЋ, Р· СЏРєРѕС— РјРѕР¶РЅР° СЃРїРёСЃР°С‚Рё Р·Р°Р»РёС€РѕРє.",
            )

    remaining = quantity_to_remove
    for batch in batches:
        batch_available = quantize_quantity(Decimal(str(batch.available_quantity or 0)))
        if batch_available <= 0:
            continue
        take = min(batch_available, remaining)
        batch.available_quantity = quantize_quantity(batch_available - take)
        remaining = quantize_quantity(remaining - take)
        if remaining <= 0:
            break

    if remaining > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"РќРµРґРѕСЃС‚Р°С‚РЅСЊРѕ РїР°СЂС‚С–Р№РЅРѕРіРѕ Р·Р°Р»РёС€РєСѓ, С‰РѕР± СЃРєРѕСЂРёРіСѓРІР°С‚Рё С‚РѕРІР°СЂ В«{product.name}В».",
        )


async def apply_stock_document(
    db: AsyncSession,
    payload: ProductStockDocumentApply,
    *,
    actor_user_id: int | None = None,
) -> ProductStockDocumentResult:
    created_count = 0
    updated_count = 0
    touched_products: list[Product] = []

    supplier = None
    document: StockDocument | None = None

    try:
        supplier = await _get_or_create_supplier(
            db,
            name=payload.supplier_name,
            phone=payload.supplier_phone,
            email=payload.supplier_email,
            notes=payload.supplier_notes,
        )
        document = StockDocument(
            document_number=payload.document_number or build_document_number(payload.document_type),
            document_type=payload.document_type,
            document_date=payload.document_date,
            supplier_id=supplier.id if supplier is not None else None,
            created_by_user_id=actor_user_id,
            note=payload.note,
        )
        db.add(document)
        await db.flush()

        for row in payload.items:
            product = await get_product_by_name_and_unit_for_update(db, name=row.name, unit=row.unit)
            if product is None:
                if payload.document_type == StockDocumentType.INVENTORY_COUNT and row.quantity_value == 0:
                    product = None
                else:
                    product = await _create_product_from_document_row(row)
                    db.add(product)
                    await db.flush()
                    created_count += 1
                    touched_products.append(product)
            else:
                updated_count += 1
                touched_products.append(product)

            document_item = StockDocumentItem(
                document_id=document.id,
                product_id=product.id if product is not None else None,
                product_name=row.name,
                unit=row.unit,
                quantity_value=quantize_quantity(row.quantity_value),
                applied_delta=Decimal("0.000"),
                sale_unit_price=quantize_money(row.sale_unit_price) if row.sale_unit_price is not None else None,
                purchase_unit_price=(
                    quantize_money(row.purchase_unit_price) if row.purchase_unit_price is not None else None
                ),
                batch_code=row.batch_code,
                serial_code=row.serial_code,
                expires_at=row.expires_at,
                note=row.note,
            )
            db.add(document_item)
            await db.flush()

            if product is None:
                continue

            if row.sale_unit_price is not None:
                product.base_unit_price = quantize_money(row.sale_unit_price)
            if row.purchase_unit_price is not None:
                product.last_purchase_price = quantize_money(row.purchase_unit_price)

            current_available = quantize_quantity(Decimal(str(product.available_quantity or 0)))
            current_reserved = quantize_quantity(Decimal(str(product.reserved_quantity or 0)))
            current_on_hand = quantize_quantity(current_available + current_reserved)

            if payload.document_type == StockDocumentType.INVENTORY_COUNT:
                target_total = quantize_quantity(row.quantity_value)
                if target_total < current_reserved:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=(
                            f"Р†РЅРІРµРЅС‚Р°СЂРёР·Р°С†С–СЏ РґР»СЏ С‚РѕРІР°СЂСѓ В«{product.name}В» РјРµРЅС€Р° Р·Р° РІР¶Рµ Р·Р°СЂРµР·РµСЂРІРѕРІР°РЅРёР№ Р·Р°Р»РёС€РѕРє. "
                            "РЎРїРѕС‡Р°С‚РєСѓ РїРѕС‚СЂС–Р±РЅРѕ РІС–РґРІР°РЅС‚Р°Р¶РёС‚Рё Р°Р±Рѕ Р·РЅСЏС‚Рё СЂРµР·РµСЂРІ."
                        ),
                    )
                delta = quantize_quantity(target_total - current_on_hand)
                product.available_quantity = quantize_quantity(target_total - current_reserved)
            else:
                delta = quantize_quantity(row.quantity_value)
                new_available = quantize_quantity(current_available + delta)
                if new_available < 0:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Р’С–Р»СЊРЅРёР№ Р·Р°Р»РёС€РѕРє РґР»СЏ С‚РѕРІР°СЂСѓ В«{product.name}В» РЅРµ РјРѕР¶Рµ Р±СѓС‚Рё РјРµРЅС€РёРј Р·Р° РЅСѓР»СЊ.",
                    )
                product.available_quantity = new_available

            document_item.applied_delta = delta

            if delta > 0:
                batch = await _find_or_create_batch_for_increase(
                    db,
                    product=product,
                    supplier=supplier,
                    document=document,
                    document_item=document_item,
                    row=row,
                )
                batch.original_quantity = quantize_quantity(Decimal(str(batch.original_quantity or 0)) + delta)
                batch.available_quantity = quantize_quantity(Decimal(str(batch.available_quantity or 0)) + delta)
            elif delta < 0:
                await _decrease_batches(
                    db,
                    product=product,
                    row=row,
                    quantity_to_remove=quantize_quantity(-delta),
                )

        await db.commit()
        await db.refresh(document)
        return ProductStockDocumentResult(
            document=document,
            created_count=created_count,
            updated_count=updated_count,
            touched_products=touched_products,
        )
    except HTTPException:
        await db.rollback()
        raise
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Складський документ не вдалося зберегти через конфлікт даних.",
        ) from exc
    except SQLAlchemyError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="РџС�async def consume_order_stock_for_pickup(db: AsyncSession, order: Order) -> None:
    product_ids = [item.product_id for item in order.items if item.product_id is not None]
    products = await get_products_for_update(db, product_ids)

    for item in order.items:
        if item.product_id is None:
            continue
        product = products.get(item.product_id)
        if product is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Товар для позиції замовлення «{item.product_name}» більше не знайдено в каталозі.",
            )

        quantity = quantize_quantity(Decimal(str(item.quantity)))

        # NOTE: ensure_opening_batch MUST be called BEFORE consume_reserved_quantity.
        # After consuming reserved, product.stock_on_hand drops to 0, and
        # ensure_opening_batch would find nothing to materialise into a batch row —
        # leaving batches empty and causing the "Not enough batch stock" error below.
        await ensure_opening_batch_for_product(db, product)

        # Remove the quantity from the product-level reserved counter.
        consume_reserved_quantity(product, quantity)

        # Deduct from physical batch rows (FIFO).
        # Use include_empty=True so we can still match batches whose available_quantity
        # is already 0 but whose reserved units belong to this order.
        batches = await _load_batches_for_update(db, product_id=product.id, include_empty=True)

        remaining = quantity
        for batch in batches:
            batch_available = quantize_quantity(Decimal(str(batch.available_quantity or 0)))
            if batch_available <= 0:
                continue
            take = min(batch_available, remaining)
            batch.available_quantity = quantize_quantity(batch_available - take)
            allocation = OrderItemBatchAllocation(
                order_item_id=item.id,
                batch_id=batch.id,
                quantity=take,
            )
            db.add(allocation)
            remaining = quantize_quantity(remaining - take)
            if remaining <= 0:
                break

        if remaining > 0:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Для товару «{item.product_name}» не вистачає партійного залишку для видачі. "
                    "Потрібно звірити накладні або оновити складські залишки."
                ),
            )€Рµ РЅРµ Р·РЅР°Р№РґРµРЅРѕ РІ РєР°С‚Р°Р»РѕР·С–.",
            )

        quantity = quantize_quantity(Decimal(str(item.quantity)))
        consume_reserved_quantity(product, quantity)
        await ensure_opening_batch_for_product(db, product)
        batches = await _load_batches_for_update(db, product_id=product.id, include_empty=False)

        remaining = quantity
        for batch in batches:
            batch_available = quantize_quantity(Decimal(str(batch.available_quantity or 0)))
            if batch_available <= 0:
                continue
            take = min(batch_available, remaining)
            batch.available_quantity = quantize_quantity(batch_available - take)
            allocation = OrderItemBatchAllocation(
                order_item_id=item.id,
                batch_id=batch.id,
                quantity=take,
            )
            db.add(allocation)
            remaining = quantize_quantity(remaining - take)
            if remaining <= 0:
                break

        if remaining > 0:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Р”Р»СЏ С‚РѕРІР°СЂСѓ В«{item.product_name}В» РЅРµ РІРёСЃС‚Р°С‡Р°С” РїР°СЂС‚С–Р№РЅРѕРіРѕ Р·Р°Р»РёС€РєСѓ РґР»СЏ РІРёРґР°С‡С–. "
                    "РџРѕС‚СЂС–Р±РЅРѕ Р·РІС–СЂРёС‚Рё РЅР°РєР»Р°РґРЅС– Р°Р±Рѕ РѕРЅРѕРІРёС‚Рё СЃРєР»Р°РґСЃСЊРєС– Р·Р°Р»РёС€РєРё."
                ),
            )


async def restore_pickup_to_reserved(db: AsyncSession, order: Order) -> None:
    item_ids = [item.id for item in order.items]
    if not item_ids:
        return

    allocation_result = await db.execute(
        select(OrderItemBatchAllocation)
        .options(selectinload(OrderItemBatchAllocation.batch))
        .where(OrderItemBatchAllocation.order_item_id.in_(item_ids))
        .order_by(OrderItemBatchAllocation.id.asc())
        .with_for_update()
    )
    allocations = allocation_result.scalars().all()
    allocations_by_item: dict[int, list[OrderItemBatchAllocation]] = {}
    for allocation in allocations:
        allocations_by_item.setdefault(allocation.order_item_id, []).append(allocation)

    product_ids = [item.product_id for item in order.items if item.product_id is not None]
    products = await get_products_for_update(db, product_ids)

    for item in order.items:
        if item.product_id is None:
            continue
        product = products.get(item.product_id)
        if product is None:
            continue

        quantity = quantize_quantity(Decimal(str(item.quantity)))
        restore_picked_up_quantity(product, quantity)
        for allocation in allocations_by_item.get(item.id, []):
            allocation.batch.available_quantity = quantize_quantity(
                Decimal(str(allocation.batch.available_quantity or 0)) + Decimal(str(allocation.quantity))
            )
            await db.delete(allocation)



