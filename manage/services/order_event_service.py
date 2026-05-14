from __future__ import annotations

from core.models import DeliveryStatus, Order, OrderEventLog, OrderStatus, UserRole


def log_order_event(
    *,
    db,
    order: Order,
    event_type: str,
    source: str,
    actor_user_id: int | None = None,
    actor_role: UserRole | None = None,
    previous_order_status: OrderStatus | None = None,
    new_order_status: OrderStatus | None = None,
    previous_delivery_status: DeliveryStatus | None = None,
    new_delivery_status: DeliveryStatus | None = None,
    delivery_id: int | None = None,
    message: str | None = None,
) -> None:
    db.add(
        OrderEventLog(
            order_id=order.id,
            delivery_id=delivery_id,
            actor_user_id=actor_user_id,
            actor_role=actor_role,
            source=source,
            event_type=event_type,
            previous_order_status=previous_order_status,
            new_order_status=new_order_status,
            previous_delivery_status=previous_delivery_status,
            new_delivery_status=new_delivery_status,
            message=message,
        )
    )

