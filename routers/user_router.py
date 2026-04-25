from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from jose import JWTError
from core.db import get_db
from core.models import User
from manage.docs.api_docs import USER_DOCS, ERROR_RESPONSES
from manage.schemas.auth_schema import UserCreate, UserOut, Token, UserRegisterResponse, phone_number_normalizer
from manage.services.auth_service import create_user, create_access_token, decode_token, verify_password
from sqlalchemy.orm import selectinload
router = APIRouter(prefix="/users", tags=["Users"])
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/users/login")


async def get_current_user(token: str = Depends(oauth2_scheme), db: AsyncSession = Depends(get_db)):

    try:
        payload = decode_token(token)
        user_id_str: str | None = payload.get("sub")
        if user_id_str is None:
            raise HTTPException(status_code=401, detail="Invalid authentication")
        user_id = int(user_id_str)
    except (JWTError, ValueError, TypeError):
        raise HTTPException(status_code=401, detail="Invalid token")

    stmt = (
        select(User)
        .options(
            selectinload(User.courier_profile),
            selectinload(User.customer_profile),
        )
        .where(User.id == user_id)
    )
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return user


@router.post(
    "/login",
    response_model=Token,
    summary=USER_DOCS["login"]["summary"],
    description=USER_DOCS["login"]["description"],
    responses={
        401: ERROR_RESPONSES["unauthorized"],
        422: ERROR_RESPONSES["validation"],
        500: ERROR_RESPONSES["internal"],
    },
)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
):
    identifier = form_data.username
    password = form_data.password

    phone_value = None
    try:
        phone_value = phone_number_normalizer(identifier)
    except Exception:
        phone_value = None

    if phone_value:
        stmt = select(User).where((User.phone == phone_value) | (User.email == identifier))
    else:
        stmt = select(User).where((User.email == identifier) | (User.phone == identifier))

    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if not user or not verify_password(password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email/phone or password")

    token = create_access_token({"sub": str(user.id)})
    return Token(access_token=token, token_type="bearer")


@router.post(
    "/register",
    response_model=UserRegisterResponse,
    status_code=status.HTTP_201_CREATED,
    summary=USER_DOCS["register"]["summary"],
    description=USER_DOCS["register"]["description"],
    responses={
        400: ERROR_RESPONSES["bad_request"],
        422: ERROR_RESPONSES["validation"],
        500: ERROR_RESPONSES["internal"],
    },
)
async def register_user(user_data: UserCreate, db: AsyncSession = Depends(get_db)):
    existing_user = await db.execute(
        select(User).where(
            (User.phone == user_data.phone_number) | (User.email == user_data.email)
        )
    )
    if existing_user.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User with this email or phone already exists",
        )

    user = await create_user(db, user_data)
    token = create_access_token({"sub": str(user.id)})

    return UserRegisterResponse(
        user=UserOut(
            id=user.id,
            full_name=user.full_name,
            phone=user.phone,
            email=user.email,
            role=user.role,
        ),
        access_token=token,
        token_type="bearer",
    )
