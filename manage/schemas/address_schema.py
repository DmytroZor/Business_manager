from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class AddressBase(BaseModel):
    street: str = Field(..., max_length=255)
    building: str = Field(..., min_length=1, max_length=20)
    apartment: Optional[str] = Field(None, max_length=20)
    notes: Optional[str] = None


class AddressCreate(AddressBase):
    """Схема для створення адреси"""
    pass


class AddressUpdate(BaseModel):
    """Схема для оновлення (всі поля необов'язкові)"""
    street: Optional[str] = Field(None, max_length=255)
    building: Optional[str] = Field(None, min_length=1, max_length=20)
    apartment: Optional[str] = Field(None, max_length=20)
    notes: Optional[str] = None


class AddressOut(AddressBase):
    """Схема для віддачі назовні"""
    pass

    class Config:
        from_attributes = True
