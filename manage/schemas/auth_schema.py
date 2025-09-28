from pydantic import BaseModel, Field, EmailStr, field_validator
from typing import Annotated

PhoneStr = Annotated[str, Field(regex=r'^\+?380\d{9}$')]


class UserCreate(BaseModel):
    full_name: str = Field(..., min_length=3)
    email: EmailStr
    password: str = Field(..., min_length=6)
    phone_number: str


    @field_validator("phone_number")
    @classmethod
    def phone_number_normalizer(cls, v):
        num = ''.join(filter(str.isdigit, v))
        if len(num) == 10:  # 0XXXXXXXXX
            num = '38' + num
        elif len(num) == 12 and num.startswith('38'):  # 380XXXXXXXXX
            pass
        elif len(num) == 13 and num.startswith('+380'): # +380XXXXXXXXX
            return num
        else:
            raise ValueError('Невірний номер')
        return '+' + num

class CourierCreate(BaseModel):
    vehicle_info: str = Field(min_length=8, max_length=8)


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
