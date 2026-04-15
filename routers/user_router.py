from fastapi import APIRouter, Depends, HTTPException, status, Form
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from core.db import get_db
from core.models import User
from manage.schemas.auth_schema import UserCreate, UserOut, Token, UserRegisterResponse, phone_number_normalizer
from manage.services.auth_service import create_user, create_access_token, decode_token, verify_password

router = APIRouter(prefix="/users", tags=["Users"])
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/users/login")


async def get_current_user(token: str = Depends(oauth2_scheme), db: AsyncSession = Depends(get_db)):
    try:
        payload = decode_token(token)
        user_id_str: str = payload.get("sub")
        if user_id_str is None:
            raise HTTPException(status_code=401, detail="Invalid authentication")
        user_id = int(user_id_str)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.post("/login", response_model=Token)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db)
):
    identifier = form_data.username  # тут Swagger вставить те, що ти введеш як "username"
    password = form_data.password

    # Спробуємо нормалізувати як телефон (+380...) — якщо не валідний, phone_normalizer підкине помилку
    phone_value = None
    try:
        phone_value = phone_number_normalizer(identifier)
    except Exception:
        phone_value = None

    if phone_value:
        stmt = select(User).where( (User.phone == phone_value) | (User.email == identifier) )
    else:
        stmt = select(User).where( (User.email == identifier) | (User.phone == identifier) )

    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if not user or not verify_password(password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Невірний email/телефон або пароль")

    token = create_access_token({"sub": str(user.id)})
    return Token(access_token=token, token_type="bearer")



@router.post("/register", response_model=UserRegisterResponse, status_code=status.HTTP_201_CREATED)
async def register_user(user_data: UserCreate, db: AsyncSession = Depends(get_db)):
    # Перевірка на дублікати
    existing_user = await db.execute(
        select(User).where(
            (User.phone == user_data.phone_number) | (User.email == user_data.email)
        )
    )
    if existing_user.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Користувач з таким email або телефоном вже існує"
        )

    user = await create_user(db, user_data)
    token = create_access_token({"sub": str(user.id)})

    return UserRegisterResponse(
        user=UserOut(
            id=user.id,
            full_name=user.full_name,
            phone=user.phone,
            email=user.email,
            role=user.role
        ),
        access_token=token,
        token_type="bearer"
    )
