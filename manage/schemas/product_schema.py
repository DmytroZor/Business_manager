from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, Field, field_validator

from core.models import StockDocumentType


class SortField(str, Enum):
    name = "name"
    base_unit_price = "base_unit_price"
    available_quantity = "available_quantity"
    created_at = "created_at"
    updated_at = "updated_at"


class ActiveStatus(str, Enum):
    active_products = "is_active"
    inactive_products = "inactive"
    all_products = "all"


class StockStatus(str, Enum):
    all_products = "all"
    in_stock = "in_stock"
    low_stock = "low_stock"
    out_of_stock = "out_of_stock"


class SortOrder(str, Enum):
    asc = "asc"
    desc = "desc"


def _strip_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


class ProductOut(BaseModel):
    id: int = Field(..., description="Product identifier.")
    sku: str = Field(..., description="Stock keeping unit.")
    name: str = Field(..., description="Product display name.")
    description: str | None = Field(None, description="Product description.")
    image_url: str | None = Field(None, description="Optional image shown in admin and catalog.")
    base_unit_price: Decimal = Field(..., description="Base price per unit.")
    last_purchase_price: Decimal | None = Field(None, description="Last known purchase price per unit.")
    last_purchase_at: date | None = Field(None, description="Date of the most recent purchase receipt.")
    unit: str = Field(..., description="Measurement unit, for example kg or piece.")
    available_quantity: Decimal = Field(..., description="Current free stock available for ordering.")
    reserved_quantity: Decimal = Field(..., description="Quantity reserved for open orders.")
    stock_on_hand: Decimal = Field(..., description="Total physical stock on hand.")
    is_active: bool = Field(..., description="Whether the product is available for ordering.")
    created_at: datetime = Field(..., description="Product creation timestamp (UTC).")
    updated_at: datetime = Field(..., description="Product last update timestamp (UTC).")

    model_config = {"from_attributes": True}


class ProductCreate(BaseModel):
    name: str = Field(..., max_length=200, description="Product name.")
    description: str | None = Field(None, description="Optional product description.")
    image_url: str | None = Field(None, max_length=500, description="Optional product image URL.")
    base_unit_price: Decimal = Field(..., gt=0, description="Base price greater than zero.")
    unit: str = Field(default="kg", max_length=20, description="Product unit, for example kg.")
    available_quantity: Decimal = Field(default=Decimal("0.000"), ge=0, description="Available free stock quantity.")
    is_active: bool = Field(default=True, description="Whether product is active in catalog.")

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("name cannot be empty")
        return cleaned

    @field_validator("unit")
    @classmethod
    def validate_unit(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("unit cannot be empty")
        return cleaned

    @field_validator("description", "image_url")
    @classmethod
    def validate_optional_text(cls, value: str | None) -> str | None:
        return _strip_optional_text(value)


class ProductUpdate(BaseModel):
    name: str | None = Field(None, max_length=200, description="Updated product name.")
    description: str | None = Field(None, description="Updated product description.")
    image_url: str | None = Field(None, max_length=500, description="Updated product image URL.")
    base_unit_price: Decimal | None = Field(None, gt=0, description="Updated base price.")
    unit: str | None = Field(None, max_length=20, description="Updated product unit.")
    available_quantity: Decimal | None = Field(None, ge=0, description="Updated free stock quantity.")
    is_active: bool | None = Field(None, description="Updated active status.")

    @field_validator("name")
    @classmethod
    def validate_optional_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("name cannot be empty")
        return cleaned

    @field_validator("unit")
    @classmethod
    def validate_optional_unit(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("unit cannot be empty")
        return cleaned

    @field_validator("description", "image_url")
    @classmethod
    def validate_optional_text(cls, value: str | None) -> str | None:
        return _strip_optional_text(value)


class ProductStockDocumentRow(BaseModel):
    product_id: int | None = Field(None, ge=1, description="Optional existing product identifier.")
    name: str = Field(..., max_length=200, description="Product name from the warehouse document.")
    unit: str = Field(default="kg", max_length=20, description="Measurement unit.")
    sale_unit_price: Decimal | None = Field(None, gt=0, description="Optional selling price update.")
    purchase_unit_price: Decimal | None = Field(None, gt=0, description="Optional purchase price.")
    quantity_value: Decimal = Field(..., description="Signed stock delta or absolute counted quantity.")
    batch_code: str | None = Field(None, max_length=100, description="Optional batch code.")
    serial_code: str | None = Field(None, max_length=100, description="Optional serial code.")
    expires_at: date | None = Field(None, description="Optional expiration date.")
    note: str | None = Field(None, max_length=500, description="Optional row note.")

    @field_validator("name")
    @classmethod
    def validate_document_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("name cannot be empty")
        return cleaned

    @field_validator("unit")
    @classmethod
    def validate_document_unit(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("unit cannot be empty")
        return cleaned

    @field_validator("sale_unit_price", "purchase_unit_price", mode="before")
    @classmethod
    def normalize_optional_price(cls, value):
        if value in (None, ""):
            return None
        return value

    @field_validator("product_id", mode="before")
    @classmethod
    def normalize_optional_product_id(cls, value):
        if value in (None, ""):
            return None
        return value

    @field_validator("batch_code", "serial_code", "note")
    @classmethod
    def validate_optional_text(cls, value: str | None) -> str | None:
        return _strip_optional_text(value)


class ProductStockDocumentApply(BaseModel):
    document_type: StockDocumentType = Field(..., description="Warehouse document type.")
    document_number: str | None = Field(None, max_length=100, description="Optional document number.")
    document_date: date = Field(..., description="Warehouse document date.")
    supplier_name: str | None = Field(None, max_length=200, description="Optional supplier name.")
    supplier_phone: str | None = Field(None, max_length=30, description="Optional supplier phone.")
    supplier_email: str | None = Field(None, max_length=200, description="Optional supplier email.")
    supplier_notes: str | None = Field(None, max_length=1000, description="Optional supplier note.")
    note: str | None = Field(None, max_length=2000, description="Optional document note.")
    items: list[ProductStockDocumentRow] = Field(..., min_length=1, description="Document rows.")

    @field_validator(
        "document_number",
        "supplier_name",
        "supplier_phone",
        "supplier_email",
        "supplier_notes",
        "note",
    )
    @classmethod
    def validate_optional_document_text(cls, value: str | None) -> str | None:
        return _strip_optional_text(value)
