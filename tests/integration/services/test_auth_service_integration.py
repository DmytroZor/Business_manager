import pytest
from sqlalchemy import select

from core.models import Customer, User, UserRole
from manage.schemas.auth_schema import UserCreate
from manage.services.auth_service import create_user


@pytest.mark.integration
@pytest.mark.asyncio
async def test_create_user_creates_customer_profile(db_session):
    payload = UserCreate(
        full_name="Integration Customer",
        email="integration.customer@example.com",
        password="1234567",
        phone_number="+380971112233",
        user_role=UserRole.CUSTOMER,
    )

    user = await create_user(db_session, payload)

    user_in_db = (await db_session.execute(select(User).where(User.id == user.id))).scalar_one_or_none()
    customer = (await db_session.execute(select(Customer).where(Customer.user_id == user.id))).scalar_one_or_none()

    assert user_in_db is not None
    assert customer is not None
