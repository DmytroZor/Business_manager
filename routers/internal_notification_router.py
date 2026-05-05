from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from core.db import get_db
from core.settings import settings
from manage.schemas.notification_schema import NotificationDeliveryAck, TelegramNotificationOut
from manage.services import notification_service

router = APIRouter(prefix="/internal/notifications", tags=["Internal Notifications"])


def _require_internal_token(x_internal_token: str | None = Header(default=None)) -> None:
    if not settings.internal_api_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Internal notification token is not configured",
        )
    if x_internal_token != settings.internal_api_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid internal token")


@router.get(
    "/telegram/pending",
    response_model=list[TelegramNotificationOut],
    summary="Claim pending Telegram notifications",
)
async def claim_pending_telegram_notifications(
    limit: int = Query(default=20, ge=1, le=100),
    _=Depends(_require_internal_token),
    db: AsyncSession = Depends(get_db),
):
    notifications = await notification_service.claim_pending_telegram_notifications(db, limit=limit)
    return [
        TelegramNotificationOut(
            id=notification.id,
            event_type=notification.event_type,
            telegram_chat_id=notification.telegram_chat_id,
            text=notification.text,
            created_at=notification.created_at,
        )
        for notification in notifications
    ]


@router.patch(
    "/telegram/{notification_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Acknowledge Telegram notification delivery result",
)
async def acknowledge_telegram_notification(
    notification_id: int,
    payload: NotificationDeliveryAck,
    _=Depends(_require_internal_token),
    db: AsyncSession = Depends(get_db),
):
    if payload.status == "sent":
        await notification_service.mark_notification_sent(db, notification_id)
    else:
        await notification_service.mark_notification_failed(db, notification_id, payload.error)
