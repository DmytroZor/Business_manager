from jose import JWTError, jwt
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import selectinload

from core.settings import settings
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from core.models import User
from sqlalchemy import select
from core.models import UserRole, Customer, Courier
from fastapi import HTTPException
from manage.schemas.auth_schema import PhoneNumber, UserCreate
from passlib.context import CryptContext

# auth_service

# створюємо контекст bcrypt
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(data: dict, expires_seconds: int | None = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(seconds=(expires_seconds or settings.jwt_expiration))
    to_encode.update({"exp": expire})
    encoded = jwt.encode(to_encode, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return encoded


def create_refresh_token(data: dict, expires_seconds: int | None = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(
        seconds=(expires_seconds or settings.jwt_refresh_expiration)  # напр. 7 днів
    )
    to_encode.update({"exp": expire, "type": "refresh"})
    encoded = jwt.encode(to_encode, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return encoded


def decode_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        return payload
    except JWTError:
        raise


async def get_user_by_username(db: AsyncSession, full_name: str):
    q = await db.execute(select(User).where(User.full_name == full_name))
    return q.scalar_one_or_none()


async def get_user_by_phone_number(db: AsyncSession, phone_number: PhoneNumber):
    q = await db.execute(select(User).where(User.phone == phone_number))
    return q.scalar_one_or_none()


async def create_user(db: AsyncSession, user_data: UserCreate):
    user = User(
        full_name=user_data.full_name,
        email=user_data.email,
        hashed_password=hash_password(user_data.password),
        phone=user_data.phone_number,
        telegram_id=user_data.telegram_id,
        role=user_data.user_role,
    )
    db.add(user)

    try:
        await db.flush()

        if user.role == UserRole.CUSTOMER:
            customer = Customer(user_id=user.id)
            db.add(customer)

        elif user.role == UserRole.COURIER:
            courier = Courier(user_id=user.id)
            db.add(courier)

        await db.commit()

        # Повертаємо вже свіжо завантаженого користувача
        result = await db.execute(
            select(User)
            .options(
                selectinload(User.customer_profile),
                selectinload(User.courier_profile),
            )
            .where(User.id == user.id)
        )
        user = result.scalar_one_or_none()

    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=400, detail="User with this email or phone already exists")
    except SQLAlchemyError:
        await db.rollback()
        raise HTTPException(status_code=500, detail="Database error while creating user")

    if not user:
        raise HTTPException(status_code=500, detail="User was created but could not be reloaded")

    return user


async def link_telegram_account(db: AsyncSession, user_id: int, telegram_id: str) -> User:
    normalized_telegram_id = telegram_id.strip()
    if not normalized_telegram_id:
        raise HTTPException(status_code=400, detail="telegram_id cannot be empty")

    existing_result = await db.execute(
        select(User).where(User.telegram_id == normalized_telegram_id)
    )
    existing_user = existing_result.scalar_one_or_none()
    if existing_user and existing_user.id != user_id:
        raise HTTPException(status_code=409, detail="This telegram_id is already linked to another user")

    result = await db.execute(
        select(User)
        .options(
            selectinload(User.customer_profile),
            selectinload(User.courier_profile),
        )
        .where(User.id == user_id)
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.telegram_id = normalized_telegram_id

    try:
        await db.commit()
        await db.refresh(user)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="This telegram_id is already linked to another user")
    except SQLAlchemyError:
        await db.rollback()
        raise HTTPException(status_code=500, detail="Database error while linking telegram account")

    return user
