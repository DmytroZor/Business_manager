import pytest
from fastapi import HTTPException

from core.models import Address, Customer, User, UserRole
from manage.schemas.address_schema import AddressCreate
from manage.services.address_service import address_create


@pytest.mark.integration
@pytest.mark.asyncio
async def test_address_create_detects_duplicate_location(db_session):
    user = User(
        full_name="Addr User",
        email="addr.user@example.com",
        phone="+380991112233",
        role=UserRole.CUSTOMER,
        hashed_password="hashed",
    )
    db_session.add(user)
    await db_session.flush()

    customer = Customer(user_id=user.id)
    db_session.add(customer)
    await db_session.flush()

    db_session.add(
        Address(
            customer_id=customer.id,
            street="Shevchenko",
            building="10/A",
            apartment="5",
            notes="first",
        )
    )
    await db_session.commit()

    with pytest.raises(HTTPException) as exc:
        await address_create(
            db_session,
            AddressCreate(street="Shevchenko", building="10/A", apartment="5", notes="duplicate"),
            customer_id=customer.id,
        )

    assert exc.value.status_code == 409
