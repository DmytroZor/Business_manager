import pytest
from sqlalchemy import select
from fastapi import HTTPException

from core.models import Customer, User, UserRole
from manage.schemas.auth_schema import UserCreate
from manage.services.auth_service import create_user, link_telegram_account


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


@pytest.mark.integration
@pytest.mark.asyncio
async def test_link_telegram_account_updates_user(db_session):
    payload = UserCreate(
        full_name="Telegram Customer",
        email="telegram.customer@example.com",
        password="1234567",
        phone_number="+380971112244",
        user_role=UserRole.CUSTOMER,
    )

    user = await create_user(db_session, payload)
    linked_user = await link_telegram_account(db_session, user.id, "555444333")

    user_in_db = (await db_session.execute(select(User).where(User.id == user.id))).scalar_one()
    assert linked_user.telegram_id == "555444333"
    assert user_in_db.telegram_id == "555444333"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_link_telegram_account_rejects_duplicate_identifier(db_session):
    first_user = await create_user(
        db_session,
        UserCreate(
            full_name="First Telegram",
            email="first.telegram@example.com",
            password="1234567",
            phone_number="+380971112255",
            user_role=UserRole.CUSTOMER,
            telegram_id="777888999",
        ),
    )
    second_user = await create_user(
        db_session,
        UserCreate(
            full_name="Second Telegram",
            email="second.telegram@example.com",
            password="1234567",
            phone_number="+380971112266",
            user_role=UserRole.CUSTOMER,
        ),
    )

    with pytest.raises(HTTPException) as exc:
        await link_telegram_account(db_session, second_user.id, first_user.telegram_id)

    assert exc.value.status_code == 409
