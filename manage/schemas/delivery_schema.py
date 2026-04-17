from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from core.models import DeliveryStatus


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


class DeliveryStatusUpdate(BaseModel):
    failed_reason: Optional[str] = Field(
        default=None,
        max_length=2000,
        description="Reason for failed delivery, required only for failed status",
    )


class DeliveryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

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