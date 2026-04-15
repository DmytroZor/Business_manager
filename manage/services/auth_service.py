from passlib.hash import bcrypt
from jose import JWTError, jwt
from datetime import datetime, timedelta, timezone
from core.settings import settings
from sqlalchemy.ext.asyncio import AsyncSession
from core.models import User
from sqlalchemy import select
from core.models import UserRole, Customer, Courier
from manage.schemas.auth_schema import PhoneNumber, UserCreate
from passlib.context import CryptContext

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
    user = User(full_name=user_data.full_name,
                email=user_data.email,
                hashed_password=hash_password(user_data.password),
                phone=user_data.phone_number,
                role=user_data.user_role)
    db.add(user)
    await db.flush()  # щоб згенерувався user.id

    if user.role == UserRole.CUSTOMER:
        customer = Customer(user_id=user.id)
        db.add(customer)

    elif user.role == UserRole.COURIER:
        courier = Courier(user_id=user.id)
        db.add(courier)

    await db.commit()
    await db.refresh(user)
    return user
