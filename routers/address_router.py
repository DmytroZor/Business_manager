from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from core.db import get_db
from fastapi import APIRouter, Depends, HTTPException
from manage.docs.api_docs import ADDRESS_DOCS, ERROR_RESPONSES
from manage.schemas.address_schema import AddressUpdate, AddressCreate, AddressOut

from routers.user_router import get_current_user
from manage.services import address_service
from core.models import User, Customer

router = APIRouter(prefix="/address", tags=["Address"])


@router.post(
    "/",
    response_model=AddressOut,
    status_code=201,
    summary=ADDRESS_DOCS["create"]["summary"],
    description=ADDRESS_DOCS["create"]["description"],
    responses={
        400: ERROR_RESPONSES["bad_request"],
        401: ERROR_RESPONSES["unauthorized"],
        409: ERROR_RESPONSES["conflict"],
        422: ERROR_RESPONSES["validation"],
        500: ERROR_RESPONSES["internal"],
    },
)
async def create_address(
        address: AddressCreate,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_user)
):

    result = await db.execute(
        select(Customer).where(Customer.user_id == current_user.id)
    )
    customer_profile = result.scalar_one_or_none()
    if not customer_profile:
        raise HTTPException(status_code=400, detail="Customer profile not found")

    created = await address_service.address_create(db, address, customer_profile.id)
    return created


@router.get(
    "/",
    response_model=AddressOut,
    status_code=200,
    summary=ADDRESS_DOCS["get"]["summary"],
    description=ADDRESS_DOCS["get"]["description"],
    responses={
        400: ERROR_RESPONSES["bad_request"],
        401: ERROR_RESPONSES["unauthorized"],
        404: ERROR_RESPONSES["not_found"],
        500: ERROR_RESPONSES["internal"],
    },
)
async def get_address(db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):

    result = await db.execute(
        select(Customer).where(Customer.user_id == current_user.id)
    )
    customer_profile = result.scalar_one_or_none()
    if not customer_profile:
        raise HTTPException(status_code=400, detail="Customer profile not found")
    address = await address_service.get_address_by_customer_id(db, customer_profile.id)
    if not address:
        raise HTTPException(status_code=404, detail="Address not found")
    return address


@router.put(
    "/",
    response_model=AddressOut,
    summary=ADDRESS_DOCS["update"]["summary"],
    description=ADDRESS_DOCS["update"]["description"],
    responses={
        400: ERROR_RESPONSES["bad_request"],
        401: ERROR_RESPONSES["unauthorized"],
        404: ERROR_RESPONSES["not_found"],
        409: ERROR_RESPONSES["conflict"],
        422: ERROR_RESPONSES["validation"],
        500: ERROR_RESPONSES["internal"],
    },
)
async def update_address(address_data: AddressUpdate, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user),
                         ):
    result = await db.execute(select(Customer).where(Customer.user_id == current_user.id))
    customer_profile = result.scalar_one_or_none()
    if not customer_profile:
        raise HTTPException(status_code=400, detail="Customer profile not found")
    update = await address_service.update_address(db, address_data, customer_profile.id)
    return update
