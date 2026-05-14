from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class TelegramNotificationOut(BaseModel):
    id: int
    event_type: str = Field(..., description="Notification event type.")
    telegram_chat_id: str = Field(..., description="Telegram chat identifier.")
    text: str = Field(..., description="Telegram message body.")
    created_at: datetime = Field(..., description="Notification creation timestamp.")


class NotificationDeliveryAck(BaseModel):
    status: Literal["sent", "failed"] = Field(..., description="Delivery result.")
    error: str | None = Field(default=None, description="Optional failure detail.")
