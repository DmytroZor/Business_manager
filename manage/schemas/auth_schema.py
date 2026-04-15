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
    phone_number: str = Field(..., description="Ukrainian phone number. Accepted formats include +380XXXXXXXXX and 0XXXXXXXXX.")

    @field_validator("phone_number")
    @classmethod
    def normalize(cls, v): return phone_number_normalizer(v)


class UserCreate(BaseModel):
    full_name: str = Field(..., min_length=3, description="User full name.")
    email: EmailStr = Field(..., description="Unique user email address.")
    password: str = Field(..., min_length=6, description="User password. Minimum 6 characters.")
    phone_number: str = Field(..., description="User phone number. Will be normalized to +380 format.")
    user_role: UserRole = Field(..., description="Role assigned to the new user.")

    @field_validator("phone_number")
    @classmethod
    def normalize(cls, v): return phone_number_normalizer(v)


class UserOut(BaseModel):
    id: int = Field(..., description="User identifier.")
    full_name: str = Field(..., description="User full name.")
    phone: str = Field(..., description="Normalized user phone number.")
    email: str | None = Field(None, description="User email.")
    role: UserRole = Field(..., description="User role.")


class UserRegisterResponse(BaseModel):
    user: UserOut = Field(..., description="Registered user details.")
    access_token: str = Field(..., description="JWT access token.")
    token_type: str = Field(default="bearer", description="OAuth2 token type.")


class CourierCreate(BaseModel):
    vehicle_info: str = Field(min_length=8, max_length=8, description="Courier vehicle information code.")


class Token(BaseModel):
    access_token: str = Field(..., description="JWT access token.")
    token_type: str = Field(default="bearer", description="OAuth2 token type.")
