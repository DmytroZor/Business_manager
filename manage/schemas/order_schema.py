from datetime import datetime
from decimal import Decimal, ROUND_DOWN
from typing import List

from pydantic import BaseModel, Field, field_validator

from core.models import OrderStatus


class OrderItemCreate(BaseModel):
    product_id: int = Field(..., gt=0, description="Identifier of product to add to order.")
    quantity: Decimal = Field(..., gt=0, description="Requested quantity. Up to 3 decimal places.")

    @field_validator("quantity")
    @classmethod
    def validate_quantity(cls, value: Decimal) -> Decimal:
        return value.quantize(Decimal("0.001"), rounding=ROUND_DOWN)


class OrderCreate(BaseModel):
    delivery_address_id: int = Field(..., gt=0, description="Customer delivery address identifier.")
    note: str | None = Field(default=None, max_length=2000, description="Optional order note for delivery.")
    items: List[OrderItemCreate] = Field(..., min_length=1, description="Order line items.")


class OrderItemOut(BaseModel):
    id: int = Field(..., description="Order item identifier.")
    product_id: int | None = Field(None, description="Linked product identifier.")
    product_name: str = Field(..., description="Snapshot of product name at order time.")
    product_sku: str | None = Field(None, description="Snapshot of product SKU at order time.")
    unit: str = Field(..., description="Snapshot of product unit.")
    unit_price: Decimal = Field(..., description="Snapshot of unit price.")
    quantity: Decimal = Field(..., description="Ordered quantity.")
    subtotal: Decimal = Field(..., description="Line subtotal.")

    model_config = {"from_attributes": True}


class OrderOut(BaseModel):
    id: int = Field(..., description="Order identifier.")
    customer_id: int | None = Field(None, description="Customer profile identifier.")
    delivery_address_id: int | None = Field(None, description="Delivery address identifier.")
    status: OrderStatus = Field(..., description="Current order status.")
    placed_at: datetime = Field(..., description="Order creation timestamp (UTC).")
    total_amount: Decimal = Field(..., description="Total order amount.")
    note: str | None = Field(None, description="Customer-provided note.")
    items: List[OrderItemOut] = Field(..., description="Order items.")

    model_config = {"from_attributes": True}
