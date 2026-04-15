from pydantic import BaseModel, Field, EmailStr, field_validator
from typing import Annotated
from core.models import UserRole

PhoneStr = Annotated[str, Field(pattern=r'^\+?380\d{9}$')]


def phone_number_normalizer(v: str):
    num = ''.join(filter(str.isdigit, v))
    if len(num) == 10:  # 0XXXXXXXXX
        num = '38' + num
    elif len(num) == 12 and num.startswith('38'):  # 380XXXXXXXXX
        pass
    elif len(num) == 13 and num.startswith('+380'):  # +380XXXXXXXXX
        return num
    else:
        raise ValueError('Невірний номер')
    return '+' + num


class PhoneNumber(BaseModel):
    phone_number: str

    @field_validator("phone_number")
    @classmethod
    def normalize(cls, v): return phone_number_normalizer(v)


class UserCreate(BaseModel):
    full_name: str = Field(..., min_length=3)
    email: EmailStr
    password: str = Field(..., min_length=6)
    phone_number: str
    user_role: UserRole

    @field_validator("phone_number")
    @classmethod
    def normalize(cls, v): return phone_number_normalizer(v)


class UserOut(BaseModel):
    id: int
    full_name: str
    phone: str
    email: str | None
    role: UserRole


class UserRegisterResponse(BaseModel):
    user: UserOut
    access_token: str
    token_type: str = "bearer"


class CourierCreate(BaseModel):
    vehicle_info: str = Field(min_length=8, max_length=8)


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
