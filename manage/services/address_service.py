from decimal import InvalidOperation, Decimal
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from manage.schemas.address_schema import AddressBase, AddressOut, AddressCreate, AddressUpdate
from core.models import Address, Customer
from sqlalchemy import select


async def address_create(db: AsyncSession, address_data: AddressCreate, customer_id: int):
    result = await db.execute(select(Customer).where(Customer.id == customer_id))
    customer = result.scalar_one_or_none()
    if not customer:
        raise ValueError("Customer not found")

    # якщо один-to-one і адреса вже є — можна або помилку, або оновити
    if customer.address:
        raise ValueError("Address already exists; use update")

    address = Address(
        customer_id=customer_id,
        street=address_data.street,
        building=address_data.building,
        apartment=address_data.apartment,
        notes=address_data.notes
    )
    db.add(address)
    await db.commit()
    await db.refresh(address)
    return address
