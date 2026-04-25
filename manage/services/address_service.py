from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from manage.schemas.address_schema import AddressCreate, AddressUpdate
from core.models import Address, Customer
#address_service

async def address_create(db: AsyncSession, address_data: AddressCreate, customer_id: int):
    # customer_id тут — це Customer.id
    result = await db.execute(select(Customer).where(Customer.id == customer_id))
    customer = result.scalar_one_or_none()
    if not customer:
        raise HTTPException(status_code=400, detail="Customer profile not found")

    address = Address(
        customer_id=customer.id,
        street=address_data.street,
        building=address_data.building,
        apartment=address_data.apartment,
        notes=address_data.notes
    )
    db.add(address)
    try:
        await db.commit()
        await db.refresh(address)
        return address
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Address already exists for this customer")
    except SQLAlchemyError:
        await db.rollback()
        raise HTTPException(status_code=500, detail="Database error while creating address")


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

    updates = data.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields provided for update")

    for key, value in updates.items():
        setattr(address, key, value)

    try:
        await db.commit()
        await db.refresh(address)
        return address
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Address already exists for this customer")
    except SQLAlchemyError:
        await db.rollback()
        raise HTTPException(status_code=500, detail="Database error while updating address")