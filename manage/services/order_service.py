from decimal import Decimal, ROUND_DOWN
from collections import OrderedDict

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core.models import Address, Customer, Order, OrderItem, Product, OrderStatus
from manage.schemas.order_schema import OrderCreate


def _quantize_money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_DOWN)


def _quantize_quantity(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.001"), rounding=ROUND_DOWN)


async def get_customer_by_user_id(db: AsyncSession, user_id: int) -> Customer:
    result = await db.execute(select(Customer).where(Customer.user_id == user_id))
    customer = result.scalar_one_or_none()
    if not customer:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Customer profile not found")
    return customer


def _merge_order_items(order_data: OrderCreate) -> list[tuple[int, Decimal]]:
    """
    Merge duplicate product lines into one line per product_id.
    Preserves first-seen order of products.
    """
    merged: OrderedDict[int, Decimal] = OrderedDict()

    for item in order_data.items:
        quantity = _quantize_quantity(item.quantity)
        if item.product_id in merged:
            merged[item.product_id] = _quantize_quantity(merged[item.product_id] + quantity)
        else:
            merged[item.product_id] = quantity

    return list(merged.items())


async def create_order(db: AsyncSession, user_id: int, order_data: OrderCreate) -> Order:
    order_id: int | None = None

    try:
        if not order_data.items:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Order must contain at least one item")

        customer = await get_customer_by_user_id(db, user_id)

        address_result = await db.execute(
            select(Address).where(
                Address.id == order_data.delivery_address_id,
                Address.customer_id == customer.id,
            )
        )
        address = address_result.scalar_one_or_none()
        if not address:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Delivery address does not belong to the customer",
            )

        merged_items = _merge_order_items(order_data)
        product_ids = [product_id for product_id, _ in merged_items]

        products_result = await db.execute(
            select(Product).where(Product.id.in_(product_ids))
        )
        products = {product.id: product for product in products_result.scalars().all()}

        missing_products = [product_id for product_id in product_ids if product_id not in products]
        if missing_products:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Products not found: {missing_products}",
            )

        inactive_products = [product_id for product_id in product_ids if not products[product_id].is_active]
        if inactive_products:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Inactive products in order: {inactive_products}",
            )

        order = Order(
            customer_id=customer.id,
            delivery_address_id=order_data.delivery_address_id,
            note=order_data.note,
            status=OrderStatus.PLACED,
            total_amount=Decimal("0.00"),
        )
        db.add(order)
        await db.flush()
        order_id = order.id

        total_amount = Decimal("0.00")

        for product_id, quantity in merged_items:
            product = products[product_id]

            unit_price = _quantize_money(Decimal(str(product.base_unit_price)))
            subtotal = _quantize_money(unit_price * quantity)

            order_item = OrderItem(
                order_id=order.id,
                product_id=product.id,
                product_name=product.name,
                product_sku=product.sku,
                unit=product.unit,
                unit_price=unit_price,
                quantity=quantity,
                subtotal=subtotal,
            )
            db.add(order_item)
            total_amount += subtotal

        order.total_amount = _quantize_money(total_amount)

        await db.commit()

    except HTTPException:
        await db.rollback()
        raise
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Database integrity error while creating order")
    except SQLAlchemyError:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Database error while creating order")

    if order_id is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Order was not created")

    return await get_order_by_id(db, user_id, order_id)


async def get_order_by_id(db: AsyncSession, user_id: int, order_id: int) -> Order:
    customer = await get_customer_by_user_id(db, user_id)
    result = await db.execute(
        select(Order)
        .options(selectinload(Order.items))
        .where(Order.id == order_id, Order.customer_id == customer.id)
    )
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    return order


async def get_customer_orders(db: AsyncSession, user_id: int, limit: int = 20, offset: int = 0) -> list[Order]:
    customer = await get_customer_by_user_id(db, user_id)
    result = await db.execute(
        select(Order)
        .options(selectinload(Order.items))
        .where(Order.customer_id == customer.id)
        .order_by(Order.placed_at.desc())
        .offset(offset)
        .limit(limit)
    )
    return result.scalars().all()