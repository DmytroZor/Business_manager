from decimal import Decimal, ROUND_DOWN

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core.models import Address, Customer, Order, OrderItem, Product
from manage.schemas.order_schema import OrderCreate


def _quantize_money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_DOWN)


async def get_customer_by_user_id(db: AsyncSession, user_id: int) -> Customer:
    result = await db.execute(select(Customer).where(Customer.user_id == user_id))
    customer = result.scalar_one_or_none()
    if not customer:
        raise HTTPException(status_code=400, detail="Customer profile not found")
    return customer


async def create_order(db: AsyncSession, user_id: int, order_data: OrderCreate) -> Order:
    order_id: int | None = None
    try:
        customer = await get_customer_by_user_id(db, user_id)

        address_result = await db.execute(
            select(Address).where(
                Address.id == order_data.delivery_address_id,
                Address.customer_id == customer.id,
            )
        )
        address = address_result.scalar_one_or_none()
        if not address:
            raise HTTPException(status_code=400, detail="Delivery address does not belong to the customer")

        order = Order(
            customer_id=customer.id,
            delivery_address_id=order_data.delivery_address_id,
            note=order_data.note,
            total_amount=Decimal("0.00"),
        )
        db.add(order)
        await db.flush()
        order_id = order.id

        total_amount = Decimal("0.00")
        for item in order_data.items:
            product_result = await db.execute(
                select(Product).where(Product.id == item.product_id, Product.is_active == True)
            )
            product = product_result.scalar_one_or_none()
            if not product:
                raise HTTPException(status_code=404, detail=f"Product {item.product_id} not found or inactive")

            unit_price = _quantize_money(Decimal(product.base_unit_price))
            subtotal = _quantize_money(unit_price * item.quantity)

            order_item = OrderItem(
                order_id=order.id,
                product_id=product.id,
                product_name=product.name,
                product_sku=product.sku,
                unit=product.unit,
                unit_price=unit_price,
                quantity=item.quantity,
                subtotal=subtotal,
            )
            db.add(order_item)
            total_amount += subtotal

        order.total_amount = _quantize_money(total_amount)
        await db.commit()
    except HTTPException:
        await db.rollback()
        raise
    except SQLAlchemyError:
        await db.rollback()
        raise HTTPException(status_code=500, detail="Database error while creating order")

    if order_id is None:
        raise HTTPException(status_code=500, detail="Order was not created")

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
        raise HTTPException(status_code=404, detail="Order not found")
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