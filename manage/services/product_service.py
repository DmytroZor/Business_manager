from decimal import InvalidOperation, Decimal
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from manage.schemas.product_schema import ProductCreate, ProductUpdate, SortOrder, SortField, ActiveStatus
from core.models import Product
from sqlalchemy import select
from additional import sku_generator

async def create_product(db: AsyncSession, product_data: ProductCreate):
    product = Product(name=product_data.name,
                      description=product_data.description,
                      base_unit_price=product_data.base_unit_price,
                      unit=product_data.unit,
                      is_active=product_data.is_active,
                      sku = sku_generator.generate_sku())
    db.add(product)
    await db.commit()
    await db.refresh(product)
    return product


async def get_product_by_id(db: AsyncSession, product_id: int):
    q = await db.execute(select(Product).where(Product.id == product_id))
    return q.scalar_one_or_none()


async def product_update_by_id(db: AsyncSession, product_id: int, product_data: ProductUpdate):
    product = await get_product_by_id(db, product_id)
    if not product:
        return None

    update_data = product_data.model_dump(exclude_unset=True)

    # Підготовка дозволених полів і non-nullable (щоб не перезаписати id і т.д.)
    allowed_fields = {c.name for c in Product.__table__.columns}  # наприклад: {'id','name','base_unit_price',...}
    # не дозволяємо міняти PK або created_at (за бажанням)
    prohibited = {"id", "created_at"}
    allowed_fields -= prohibited

    # Які поля у таблиці не допускають NULL
    non_nullable = {c.name for c in Product.__table__.columns if not c.nullable}
    # якщо потрібно дозволити None для деяких полів, видали їх з non_nullable

    # 3. фільтрація і перевірки
    cleaned: dict = {}
    for k, v in update_data.items():
        if k not in allowed_fields:
            # ігноруємо невідомі поля (або кидаємо помилку)
            continue

        # Якщо поле не nullable і передано explicit null -> ігноруємо або кидаємо помилку
        if v is None and k in non_nullable:
            # можна: raise ValueError(f"{k} cannot be null")
            # або просто continue (щоб не перезаписати)
            continue

        # спеціальна обробка для base_unit_price (Decimal)
        if k == "base_unit_price" and v is not None:
            # Якщо прийшло як рядок "100грн" чи "100.0" — чистимо і конвертуємо
            if isinstance(v, str):
                cleaned_str = "".join(ch for ch in v if ch.isdigit() or ch == ".")
                if cleaned_str == "":
                    continue
                try:
                    dec = Decimal(cleaned_str)
                except InvalidOperation:
                    continue  # або raise
            else:
                # якщо це число (int/float/Decimal)
                try:
                    dec = Decimal(str(v))
                except InvalidOperation:
                    continue
            # бізнес-правило: ціна > 0
            if dec <= 0:
                continue  # або raise ValueError("price must be > 0")
            cleaned[k] = dec
            continue

        # приклад: trim name та не пустий рядок
        if k == "name" and v is not None:
            v = v.strip()
            if v == "":
                continue
            cleaned[k] = v
            continue

        # приклад: unit — укоротити/перевірити довжину або перелік
        if k == "unit" and v is not None:
            v = v.strip()
            if len(v) == 0 or len(v) > 20:
                continue

            # if v not in allowed_units: continue
            cleaned[k] = v
            continue

        # is_active — привести до bool
        if k == "is_active" and v is not None:
            cleaned[k] = bool(v)
            continue

        # дефолтна дія: якщо прийшло поле яке можна просто поставити
        cleaned[k] = v

    # 4. застосувати зміни
    for field, value in cleaned.items():
        setattr(product, field, value)

    # 5. commit з rollback у випадку помилки
    try:
        await db.commit()
        await db.refresh(product)
    except SQLAlchemyError:
        await db.rollback()
        raise

    return product


async def product_delete_by_id(db: AsyncSession, product_id: int):
    product = await get_product_by_id(db, product_id)
    if not product:
        return False
    await db.delete(product)
    await db.commit()
    return True


async def get_all_products(db: AsyncSession,
                           sort_field: SortField,
                           active_status: ActiveStatus,
                           sort_order: SortOrder,
                           offset: int = 0,
                           limit: int = 10,
                           ):
    if active_status == ActiveStatus.all_products:
        products = select(Product)
    if active_status == ActiveStatus.active_products:
        products = select(Product).where(Product.is_active == True)
    if active_status == ActiveStatus.inactive_products:
        products = select(Product).where(Product.is_active == False)

    sort_col = getattr(Product, sort_field)

    if sort_order == SortOrder.desc:
        products = products.order_by(sort_col.desc())
    else:
        products = products.order_by(sort_col.asc())

    products = products.offset(offset).limit(limit)
    result = await db.execute(products)
    return result.scalars().all()
