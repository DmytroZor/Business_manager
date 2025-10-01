from pydantic import BaseModel, Field
from typing import Optional
from enum import Enum
from decimal import Decimal
from datetime import datetime

from sqlalchemy import NotNullable


class SortField(str, Enum):
    name = "name"
    base_unit_price = "base_unit_price"
    is_active = "is_active"


class SortOrder(str, Enum):
    asc = "asc"
    desc = "desc"


class ProductOut(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    base_unit_price: Decimal
    unit: str
    is_active: bool
    created_at: datetime
    model_config = {"from_attributes": True}


class ProductCreate(BaseModel):
    name: str = Field(..., max_length=200)
    description: Optional[str] = None
    base_unit_price: Decimal = Field(..., gt=0)
    unit: str = Field(default="kg", max_length=20)
    is_active: bool = True




class ProductUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=200)
    description: Optional[str] = None
    base_unit_price: Optional[Decimal] = Field(None, gt=0)
    unit: Optional[str] = Field(None, max_length=20)
    is_active: Optional[bool] = None
