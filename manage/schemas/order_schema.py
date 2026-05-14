from datetime import datetime
from decimal import Decimal, ROUND_DOWN
from typing import List

from pydantic import BaseModel, Field, field_validator

from core.models import DeliveryStatus, OrderStatus
from manage.schemas.auth_schema import phone_number_normalizer


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


class AdminOrderEventOut(BaseModel):
    id: int = Field(..., description="Event identifier.")
    event_type: str = Field(..., description="Audit event type.")
    source: str = Field(..., description="Event source.")
    actor_user_id: int | None = Field(None, description="Actor user identifier.")
    actor_role: str | None = Field(None, description="Actor role.")
    actor_name: str | None = Field(None, description="Actor full name.")
    previous_order_status: OrderStatus | None = Field(None, description="Previous order status.")
    new_order_status: OrderStatus | None = Field(None, description="New order status.")
    previous_delivery_status: DeliveryStatus | None = Field(None, description="Previous delivery status.")
    new_delivery_status: DeliveryStatus | None = Field(None, description="New delivery status.")
    message: str | None = Field(None, description="Human-friendly event note.")
    created_at: datetime = Field(..., description="Event timestamp.")


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
    events: List[AdminOrderEventOut] = Field(default_factory=list, description="Order audit timeline.")


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

    @field_validator("customer_phone_number")
    @classmethod
    def normalize_phone_number(cls, value: str) -> str:
        return phone_number_normalizer(value)


class OrderCancelPayload(BaseModel):
    reason: str | None = Field(default=None, max_length=2000, description="Optional cancellation reason.")


class AdminOrderItemQuantityUpdate(BaseModel):
    item_id: int = Field(..., gt=0, description="Order item identifier.")
    quantity: Decimal = Field(..., ge=0, description="Updated quantity. Zero removes the item.")

    @field_validator("quantity")
    @classmethod
    def validate_quantity(cls, value: Decimal) -> Decimal:
        return value.quantize(Decimal("0.001"), rounding=ROUND_DOWN)


class AdminOrderItemsUpdate(BaseModel):
    items: List[AdminOrderItemQuantityUpdate] = Field(..., min_length=1, description="Updated order line items.")
