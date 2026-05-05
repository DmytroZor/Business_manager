from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from core.models import DeliveryStatus, OrderStatus
from manage.schemas.order_schema import OrderItemOut


class DeliveryAssignCreate(BaseModel):
    courier_id: int = Field(..., gt=0, description="Courier profile ID, not user ID")
    scheduled_at: Optional[datetime] = Field(
        default=None,
        description="Optional planned pickup/delivery time",
    )
    fee: Decimal = Field(
        default=Decimal("0.00"),
        ge=0,
        description="Delivery fee",
    )


class DeliverySelfAssignCreate(BaseModel):
    scheduled_at: Optional[datetime] = Field(
        default=None,
        description="Optional planned pickup/delivery time",
    )
    fee: Decimal = Field(
        default=Decimal("0.00"),
        ge=0,
        description="Delivery fee",
    )


class DeliveryStatusUpdate(BaseModel):
    failed_reason: Optional[str] = Field(
        default=None,
        max_length=2000,
        description="Reason for failed delivery, required only for failed status",
    )


class CourierOrderAddressOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    street: str
    building: str
    apartment: str | None = None
    notes: str | None = None


class CourierOrderCustomerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    full_name: str
    phone: str


class CourierOrderOut(BaseModel):
    id: int
    status: OrderStatus
    placed_at: datetime
    total_amount: Decimal
    note: str | None = None
    delivery_address: CourierOrderAddressOut | None = None
    customer: CourierOrderCustomerOut | None = None
    items: list[OrderItemOut] = Field(default_factory=list)


class CourierAssignedInfoOut(BaseModel):
    full_name: str
    phone: str
    vehicle_info: str | None = None


class CourierDeliveryOut(BaseModel):
    id: int
    order_id: int
    courier_id: Optional[int]
    status: DeliveryStatus
    scheduled_at: Optional[datetime]
    assigned_at: Optional[datetime]
    picked_up_at: Optional[datetime]
    delivered_at: Optional[datetime]
    failed_reason: Optional[str]
    fee: Decimal
    created_at: datetime
    order: CourierOrderOut | None = None
    courier: CourierAssignedInfoOut | None = None
