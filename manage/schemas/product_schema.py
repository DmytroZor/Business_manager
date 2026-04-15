from pydantic import BaseModel, Field
from typing import Optional
from enum import Enum
from decimal import Decimal
from datetime import datetime


class SortField(str, Enum):
    name = "name"
    base_unit_price = "base_unit_price"


class ActiveStatus(str, Enum):
    active_products = 'is_active'
    inactive_products = 'inactive'
    all_products = "all"


class SortOrder(str, Enum):
    asc = "asc"
    desc = "desc"


class ProductOut(BaseModel):
    id: int = Field(..., description="Product identifier.")
    sku: str = Field(..., description="Stock keeping unit.")
    name: str = Field(..., description="Product display name.")
    description: Optional[str] = Field(None, description="Product description.")
    base_unit_price: Decimal = Field(..., description="Base price per unit.")
    unit: str = Field(..., description="Measurement unit, for example kg or piece.")
    is_active: bool = Field(..., description="Whether the product is available for ordering.")
    created_at: datetime = Field(..., description="Product creation timestamp (UTC).")
    model_config = {"from_attributes": True}


class ProductCreate(BaseModel):
    name: str = Field(..., max_length=200, description="Product name.")
    description: Optional[str] = Field(None, description="Optional product description.")
    base_unit_price: Decimal = Field(..., gt=0, description="Base price greater than zero.")
    unit: str = Field(default="kg", max_length=20, description="Product unit, for example kg.")
    is_active: bool = Field(default=True, description="Whether product is active in catalog.")




class ProductUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=200, description="Updated product name.")
    description: Optional[str] = Field(None, description="Updated product description.")
    base_unit_price: Optional[Decimal] = Field(None, gt=0, description="Updated base price.")
    unit: Optional[str] = Field(None, max_length=20, description="Updated product unit.")
    is_active: Optional[bool] = Field(None, description="Updated active status.")
