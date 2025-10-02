from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class AddressBase(BaseModel):
    street: str = Field(..., max_length=255)
    building: Optional[str] = Field(None, max_length=50)
    apartment: Optional[str] = Field(None, max_length=50)
    notes: Optional[str] = None


class AddressCreate(AddressBase):
    """Схема для створення адреси"""
    pass


class AddressUpdate(BaseModel):
    """Схема для оновлення (всі поля необов'язкові)"""
    street: Optional[str] = Field(None, max_length=255)
    building: Optional[str] = Field(None, max_length=50)
    apartment: Optional[str] = Field(None, max_length=50)
    notes: Optional[str] = None


class AddressOut(AddressBase):
    """Схема для віддачі назовні"""
    id: int
    customer_id: int
    created_at: datetime

    class Config:
        from_attributes = True   # щоб працювало з ORM
