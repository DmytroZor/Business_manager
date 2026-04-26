from datetime import datetime
from decimal import Decimal, ROUND_DOWN
from typing import List

from pydantic import BaseModel, Field, field_validator

from core.models import DeliveryStatus, OrderStatus


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


class AdminOrderCustomerInfo(BaseModel):
    user_id: int | None = Field(None, description="User identifier.")
    customer_id: int | None = Field(None, description="Customer profile identifier.")
    full_name: str = Field(..., description="Customer full name.")
    phone: str = Field(..., description="Customer phone.")
    email: str | None = Field(None, description="Customer email.")


class AdminOrderAddressInfo(BaseModel):
    id: int | None = Field(None, description="Address identifier.")
    street: str = Field(..., description="Street.")
    building: str = Field(..., description="Building.")
    apartment: str | None = Field(None, description="Apartment or office.")
    notes: str | None = Field(None, description="Delivery notes.")


class AdminOrderCourierInfo(BaseModel):
    courier_id: int | None = Field(None, description="Courier profile identifier.")
    user_id: int | None = Field(None, description="Courier user identifier.")
    full_name: str = Field(..., description="Courier full name.")
    phone: str = Field(..., description="Courier phone.")
    telegram_id: str | None = Field(None, description="Courier Telegram identifier.")


class AdminOrderDeliveryInfo(BaseModel):
    id: int = Field(..., description="Delivery identifier.")
    status: DeliveryStatus = Field(..., description="Delivery status.")
    scheduled_at: datetime | None = Field(None, description="Scheduled delivery time.")
    assigned_at: datetime | None = Field(None, description="Assignment time.")
    picked_up_at: datetime | None = Field(None, description="Pickup time.")
    delivered_at: datetime | None = Field(None, description="Delivery time.")
    failed_reason: str | None = Field(None, description="Failure reason.")
    fee: Decimal = Field(..., description="Delivery fee.")
    courier: AdminOrderCourierInfo | None = Field(None, description="Assigned courier details.")


class AdminOrderOut(BaseModel):
    id: int = Field(..., description="Order identifier.")
    status: OrderStatus = Field(..., description="Order status.")
    placed_at: datetime = Field(..., description="Order creation time.")
    total_amount: Decimal = Field(..., description="Order total.")
    note: str | None = Field(None, description="Order note.")
    customer: AdminOrderCustomerInfo | None = Field(None, description="Customer information.")
    delivery_address: AdminOrderAddressInfo | None = Field(None, description="Delivery address.")
    items: List[OrderItemOut] = Field(..., description="Order items.")
    active_delivery: AdminOrderDeliveryInfo | None = Field(None, description="Active delivery information.")


class AdminPhoneOrderCreate(BaseModel):
    customer_full_name: str = Field(..., min_length=3, description="Customer full name.")
    customer_phone_number: str = Field(..., description="Customer phone number.")
    customer_email: str | None = Field(default=None, description="Optional customer email.")
    street: str = Field(..., min_length=2, description="Delivery street.")
    building: str = Field(..., min_length=1, description="Delivery building.")
    apartment: str | None = Field(default=None, description="Optional apartment or office.")
    address_notes: str | None = Field(default=None, max_length=2000, description="Optional address notes.")
    note: str | None = Field(default=None, max_length=2000, description="Optional order note.")
    items: List[OrderItemCreate] = Field(..., min_length=1, description="Order line items.")


class OrderCancelPayload(BaseModel):
    reason: str | None = Field(default=None, max_length=2000, description="Optional cancellation reason.")
