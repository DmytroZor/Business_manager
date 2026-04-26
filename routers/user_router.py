from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core.db import get_db
from core.models import User
from manage.docs.api_docs import ERROR_RESPONSES, USER_DOCS
from manage.schemas.auth_schema import (
    AdminUserSummaryOut,
    TelegramLinkPayload,
    Token,
    UserCreate,
    UserOut,
    UserRegisterResponse,
    phone_number_normalizer,
)
from core.models import UserRole
from manage.services.auth_service import (
    create_access_token,
    create_user,
    decode_token,
    link_telegram_account,
    verify_password,
)

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
            telegram_id=user.telegram_id,
            role=user.role,
        ),
        access_token=token,
        token_type="bearer",
    )


@router.post(
    "/me/telegram-link",
    response_model=UserOut,
    summary=USER_DOCS["telegram_link"]["summary"],
    description=USER_DOCS["telegram_link"]["description"],
    responses={
        401: ERROR_RESPONSES["unauthorized"],
        409: ERROR_RESPONSES["conflict"],
        422: ERROR_RESPONSES["validation"],
        500: ERROR_RESPONSES["internal"],
    },
)
async def connect_telegram_account(
    payload: TelegramLinkPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user = await link_telegram_account(db, current_user.id, payload.telegram_id)
    return UserOut(
        id=user.id,
        full_name=user.full_name,
        phone=user.phone,
        email=user.email,
        telegram_id=user.telegram_id,
        role=user.role,
    )


@router.get(
    "/admin/couriers",
    response_model=list[AdminUserSummaryOut],
    summary="Admin: list couriers",
    description="Returns couriers available for assignment in admin tools.",
)
async def admin_list_couriers(
    active_only: bool = Query(default=True),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")

    stmt = (
        select(User)
        .options(selectinload(User.courier_profile))
        .where(User.role == UserRole.COURIER)
        .order_by(User.full_name.asc())
    )
    if active_only:
        stmt = stmt.where(User.is_active.is_(True))

    result = await db.execute(stmt)
    couriers = result.scalars().all()

    return [
        AdminUserSummaryOut(
            user_id=user.id,
            profile_id=user.courier_profile.id if user.courier_profile else None,
            full_name=user.full_name,
            phone=user.phone,
            email=user.email,
            telegram_id=user.telegram_id,
            role=user.role,
            is_active=user.is_active,
            vehicle_info=user.courier_profile.vehicle_info if user.courier_profile else None,
        )
        for user in couriers
    ]
