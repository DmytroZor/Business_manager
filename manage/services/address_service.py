from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from manage.schemas.address_schema import AddressCreate, AddressUpdate, AddressOut
from core.models import Address, Customer


async def address_create(db: AsyncSession, address_data: AddressCreate, customer_id: int):
    # customer_id тут — це Customer.id
    result = await db.execute(select(Customer).where(Customer.id == customer_id))
    customer = result.scalar_one_or_none()
    if not customer:
        raise HTTPException(status_code=400, detail="Customer profile not found")

    # НЕ звертаємось до customer.addresses (avoid lazy load).
    # Замість цього явно перевіряємо, чи існує адреса в таблиці:
    addr_check = await db.execute(select(Address).where(Address.customer_id == customer.id))
    existing_addr = addr_check.scalar_one_or_none()
    if existing_addr:
        raise HTTPException(status_code=400, detail="Address already exists; use update")

    address = Address(
        customer_id=customer.id,
        street=address_data.street,
        building=address_data.building,
        apartment=address_data.apartment,
        notes=address_data.notes
    )
    db.add(address)
    await db.commit()
    await db.refresh(address)
    return address


async def get_address_by_customer_id(db: AsyncSession, customer_id: int):

    result = await db.execute(
        select(Address).where(Address.customer_id == customer_id)
    )
    return result.scalar_one_or_none()


async def update_address(db: AsyncSession, data: AddressUpdate, customer_id: int):
    q = await db.execute(
        select(Address).where(Address.customer_id == customer_id)
    )
    address = q.scalar_one_or_none()
    if not address:
        raise HTTPException(status_code=404, detail="Адресу не знайдено")

    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(address, key, value)

    await db.commit()
    await db.refresh(address)
    return address