from datetime import datetime
from decimal import Decimal, ROUND_DOWN
from typing import List

from pydantic import BaseModel, Field, field_validator

from core.models import OrderStatus


class OrderItemCreate(BaseModel):
    product_id: int = Field(..., gt=0)
    quantity: Decimal = Field(..., gt=0)

    @field_validator("quantity")
    @classmethod
    def validate_quantity(cls, value: Decimal) -> Decimal:
        return value.quantize(Decimal("0.001"), rounding=ROUND_DOWN)


class OrderCreate(BaseModel):
    delivery_address_id: int = Field(..., gt=0)
    note: str | None = Field(default=None, max_length=2000)
    items: List[OrderItemCreate] = Field(..., min_length=1)


class OrderItemOut(BaseModel):
    id: int
    product_id: int | None
    product_name: str
    product_sku: str | None
    unit: str
    unit_price: Decimal
    quantity: Decimal
    subtotal: Decimal

    model_config = {"from_attributes": True}


class OrderOut(BaseModel):
    id: int
    customer_id: int | None
    delivery_address_id: int | None
    status: OrderStatus
    placed_at: datetime
    total_amount: Decimal
    note: str | None
    items: List[OrderItemOut]

    model_config = {"from_attributes": True}
