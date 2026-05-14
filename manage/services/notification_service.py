from __future__ import annotations

import html
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Sequence

from sqlalchemy import or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from core.models import (
    Delivery,
    DeliveryStatus,
    NotificationChannel,
    NotificationDelivery,
    NotificationDeliveryStatus,
    Order,
    OrderStatus,
    User,
    UserRole,
)
from core.time_utils import format_kyiv_datetime

logger = logging.getLogger(__name__)

STALE_PROCESSING_AFTER = timedelta(minutes=5)


def _escape(value: object) -> str:
    return html.escape(str(value))


def _money(value: object) -> str:
    amount = Decimal(str(value or 0))
    return f"{amount:.2f} грн"


def _quantity(value: object) -> str:
    amount = Decimal(str(value or 0)).normalize()
    text = format(amount, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _format_datetime(value: object | None) -> str:
    return format_kyiv_datetime(value)


def _order_status_label(status_value: OrderStatus | None) -> str:
    mapping = {
        OrderStatus.PLACED: "Прийнято",
        OrderStatus.PREPARING: "Готуємо",
        OrderStatus.OUT_FOR_DELIVERY: "Передано в доставку",
        OrderStatus.DELIVERED: "Доставлено",
        OrderStatus.CANCELLED: "Скасовано",
        OrderStatus.PAID: "Оплачено",
        OrderStatus.DRAFT: "Чернетка",
    }
    return mapping.get(status_value, str(status_value.value if status_value else "-"))


def _customer_block(order: Order) -> tuple[str, str, str]:
    full_name = "Невідомий клієнт"
    phone = "-"
    email = "-"
    if order.customer is not None and order.customer.user is not None:
        full_name = order.customer.user.full_name
        phone = order.customer.user.phone
        email = order.customer.user.email or "-"
    return full_name, phone, email


def _address_block(order: Order) -> str:
    address = order.delivery_address
    if address is None:
        return "Адресу доставки ще не вказано"
    parts = [address.street, address.building]
    if address.apartment:
        parts.append(address.apartment)
    text = ", ".join(_escape(part) for part in parts if part)
    if address.notes:
        text = f"{text}\nПримітка: {_escape(address.notes)}"
    return text


def _items_block(order: Order) -> str:
    if not order.items:
        return "Позиції відсутні"
    lines = []
    for item in order.items:
        lines.append(
            f"• {_escape(item.product_name)} — {_quantity(item.quantity)} {_escape(item.unit)} на {_money(item.subtotal)}"
        )
    return "\n".join(lines)


def _active_delivery(order: Order) -> Delivery | None:
    if not order.deliveries:
        return None
    priorities = {
        DeliveryStatus.PICKED_UP: 4,
        DeliveryStatus.ASSIGNED: 3,
        DeliveryStatus.PENDING: 2,
        DeliveryStatus.DELIVERED: 1,
        DeliveryStatus.FAILED: 0,
    }
    return max(
        order.deliveries,
        key=lambda delivery: (
            priorities.get(delivery.status, -1),
            delivery.created_at or delivery.assigned_at,
        ),
    )


def _customer_user(order: Order) -> User | None:
    if order.customer is None:
        return None
    return order.customer.user


def build_new_order_admin_text(order: Order) -> str:
    customer_name, phone, email = _customer_block(order)
    return (
        "<b>Нове замовлення</b>\n"
        f"Замовлення: <b>#{order.id}</b>\n"
        f"Оформлено: {_escape(_format_datetime(order.placed_at))}\n"
        f"Клієнт: <b>{_escape(customer_name)}</b>\n"
        f"Телефон: <code>{_escape(phone)}</code>\n"
        f"Email: {_escape(email)}\n"
        f"Сума: <b>{_money(order.total_amount)}</b>\n"
        f"Адреса: {_address_block(order)}\n\n"
        "<b>Склад замовлення</b>\n"
        f"{_items_block(order)}"
    )


def build_new_order_courier_text(order: Order) -> str:
    return (
        "<b>Нове замовлення для доставки</b>\n"
        f"Замовлення: <b>#{order.id}</b>\n"
        f"Оформлено: {_escape(_format_datetime(order.placed_at))}\n"
        f"Сума: <b>{_money(order.total_amount)}</b>\n"
        f"Адреса: {_address_block(order)}\n\n"
        "Зайдіть у меню кур'єра в Telegram, щоб переглянути доступні замовлення."
    )


def build_delivery_assigned_text(order: Order, courier_name: str) -> str:
    return (
        "<b>Вам призначили доставку</b>\n"
        f"Замовлення: <b>#{order.id}</b>\n"
        f"Кур'єр: <b>{_escape(courier_name)}</b>\n"
        f"Сума: <b>{_money(order.total_amount)}</b>\n"
        f"Адреса: {_address_block(order)}\n\n"
        "Відкрийте меню кур'єра в Telegram, щоб побачити деталі доставки."
    )


def build_new_order_courier_text_v2(order: Order) -> str:
    return (
        "<b>На сьогодні з’явилося нове вільне замовлення</b>\n"
        f"Замовлення: <b>#{order.id}</b>\n"
        f"Оформлено: {_escape(_format_datetime(order.placed_at))}\n"
        f"Сума: <b>{_money(order.total_amount)}</b>\n"
        f"Адреса: {_address_block(order)}\n\n"
        "Зайдіть у розділ <b>«Вільні замовлення на сьогодні»</b>, якщо готові взяти це замовлення в роботу."
    )


def build_delivery_assigned_text_v2(order: Order) -> str:
    return (
        "<b>Для вас призначили доставку</b>\n"
        f"Замовлення: <b>#{order.id}</b>\n"
        f"Оформлено: {_escape(_format_datetime(order.placed_at))}\n"
        f"Сума: <b>{_money(order.total_amount)}</b>\n"
        f"Адреса: {_address_block(order)}\n\n"
        "Відкрийте розділ <b>«Мої доставки»</b>, щоб побачити деталі та змінити статус, коли заберете замовлення."
    )


def build_courier_cancelled_text(order: Order, reason: str | None) -> str:
    lines = [
        "<b>Замовлення скасовано менеджером</b>",
        f"Замовлення: <b>#{order.id}</b>",
        f"Оформлено: {_escape(_format_datetime(order.placed_at))}",
        f"Адреса: {_address_block(order)}",
    ]
    if reason:
        lines.append(f"Причина: {_escape(reason)}")
    lines.extend(["", "Це замовлення більше не потрібно доставляти."])
    return "\n".join(lines)


def build_customer_status_text(
    order: Order,
    *,
    previous_status: OrderStatus | None,
    new_status: OrderStatus,
    source: str,
    delivery: Delivery | None = None,
) -> str:
    lines = [
        "<b>Є оновлення по вашому замовленню</b>",
        f"Замовлення: <b>#{order.id}</b>",
        f"Було: {_escape(_order_status_label(previous_status)) if previous_status else '-'}",
        f"Зараз: <b>{_escape(_order_status_label(new_status))}</b>",
    ]

    current_delivery = delivery or _active_delivery(order)
    courier_user = None
    if current_delivery is not None and current_delivery.courier is not None:
        courier_user = current_delivery.courier.user

    if new_status == OrderStatus.PREPARING:
        lines.append("Ми підтвердили замовлення й уже готуємо його до відправлення.")
        if courier_user is not None:
            lines.append(f"Ваш кур'єр: <b>{_escape(courier_user.full_name)}</b>")
            lines.append(f"Телефон кур'єра: <code>{_escape(courier_user.phone)}</code>")
    elif new_status == OrderStatus.OUT_FOR_DELIVERY:
        lines.append("Кур'єр уже забрав замовлення — воно в дорозі до вас.")
        if courier_user is not None:
            lines.append(f"Кур'єр: <b>{_escape(courier_user.full_name)}</b>")
            lines.append(f"Телефон кур'єра: <code>{_escape(courier_user.phone)}</code>")
    elif new_status == OrderStatus.DELIVERED:
        lines.append("Замовлення позначено як доставлене. Сподіваємося, все смакуватиме.")
    elif new_status == OrderStatus.CANCELLED:
        lines.append("Замовлення скасовано. Якщо потрібні деталі, будь ласка, зв'яжіться з менеджером.")
    else:
        if source == "admin_panel":
            lines.append("Оновлення внесла команда магазину.")
        elif source == "telegram_bot":
            lines.append("Статус змінився після дії в Telegram.")
        else:
            lines.append(f"Джерело оновлення: {_escape(source)}")

    return "\n".join(lines)


async def _users_for_role(db: AsyncSession, role: UserRole) -> Sequence[User]:
    result = await db.execute(
        select(User).where(
            User.role == role,
            User.is_active.is_(True),
            User.telegram_id.is_not(None),
        )
    )
    return result.scalars().all()


async def _create_notifications_for_users(
    db: AsyncSession,
    *,
    users: Sequence[User],
    event_type: str,
    text: str,
    recipient_role: UserRole | None = None,
    order_id: int | None = None,
    delivery_id: int | None = None,
) -> int:
    created = 0
    for user in users:
        if not user.telegram_id:
            continue
        db.add(
            NotificationDelivery(
                event_type=event_type,
                channel=NotificationChannel.TELEGRAM,
                status=NotificationDeliveryStatus.PENDING,
                recipient_role=recipient_role or user.role,
                recipient_user_id=user.id,
                telegram_chat_id=user.telegram_id,
                text=text,
                order_id=order_id,
                delivery_id=delivery_id,
            )
        )
        created += 1
    return created


async def enqueue_new_order_notifications(db: AsyncSession, order: Order) -> int:
    admins = await _users_for_role(db, UserRole.ADMIN)
    couriers = await _users_for_role(db, UserRole.COURIER)
    created = 0
    created += await _create_notifications_for_users(
        db,
        users=admins,
        event_type="order_created_admin",
        text=build_new_order_admin_text(order),
        recipient_role=UserRole.ADMIN,
        order_id=order.id,
    )
    created += await _create_notifications_for_users(
        db,
        users=couriers,
        event_type="order_created_courier",
        text=build_new_order_courier_text_v2(order),
        recipient_role=UserRole.COURIER,
        order_id=order.id,
    )
    return created


async def enqueue_delivery_assigned_notification(
    db: AsyncSession,
    *,
    order: Order,
    delivery: Delivery,
    courier_user: User,
) -> int:
    if not courier_user.telegram_id:
        return 0
    return await _create_notifications_for_users(
        db,
        users=[courier_user],
        event_type="delivery_assigned",
        text=build_delivery_assigned_text_v2(order),
        recipient_role=UserRole.COURIER,
        order_id=order.id,
        delivery_id=delivery.id,
    )


async def enqueue_courier_order_cancelled_notification(
    db: AsyncSession,
    *,
    order: Order,
    courier_users: Sequence[User],
    reason: str | None,
) -> int:
    users = [user for user in courier_users if user.telegram_id]
    if not users:
        return 0
    return await _create_notifications_for_users(
        db,
        users=users,
        event_type="order_cancelled_courier",
        text=build_courier_cancelled_text(order, reason),
        recipient_role=UserRole.COURIER,
        order_id=order.id,
    )


async def enqueue_order_status_notifications(
    db: AsyncSession,
    *,
    order: Order,
    previous_status: OrderStatus | None,
    new_status: OrderStatus,
    source: str,
    delivery: Delivery | None = None,
) -> int:
    customer_user = _customer_user(order)
    if customer_user is None or not customer_user.telegram_id:
        return 0
    return await _create_notifications_for_users(
        db,
        users=[customer_user],
        event_type="order_status_changed_customer",
        text=build_customer_status_text(
            order,
            previous_status=previous_status,
            new_status=new_status,
            source=source,
            delivery=delivery,
        ),
        recipient_role=UserRole.CUSTOMER,
        order_id=order.id,
        delivery_id=delivery.id if delivery is not None else None,
    )


async def claim_pending_telegram_notifications(
    db: AsyncSession,
    *,
    limit: int = 20,
) -> list[NotificationDelivery]:
    now = datetime.now(timezone.utc)
    stale_before = now - STALE_PROCESSING_AFTER
    stmt = (
        select(NotificationDelivery)
        .where(NotificationDelivery.channel == NotificationChannel.TELEGRAM)
        .where(
            or_(
                NotificationDelivery.status == NotificationDeliveryStatus.PENDING,
                (
                    NotificationDelivery.status == NotificationDeliveryStatus.PROCESSING
                ) & (
                    NotificationDelivery.processing_started_at.is_not(None)
                ) & (
                    NotificationDelivery.processing_started_at < stale_before
                ),
            )
        )
        .order_by(NotificationDelivery.created_at.asc())
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    result = await db.execute(stmt)
    notifications = result.scalars().all()
    for notification in notifications:
        notification.status = NotificationDeliveryStatus.PROCESSING
        notification.processing_started_at = now
        notification.attempt_count = int(notification.attempt_count or 0) + 1
        notification.last_error = None
    await db.commit()
    return notifications


async def mark_notification_sent(db: AsyncSession, notification_id: int) -> None:
    result = await db.execute(
        select(NotificationDelivery).where(NotificationDelivery.id == notification_id)
    )
    notification = result.scalar_one_or_none()
    if notification is None:
        return
    notification.status = NotificationDeliveryStatus.SENT
    notification.sent_at = datetime.now(timezone.utc)
    notification.processing_started_at = None
    notification.last_error = None
    await db.commit()


async def mark_notification_failed(db: AsyncSession, notification_id: int, error: str | None) -> None:
    result = await db.execute(
        select(NotificationDelivery).where(NotificationDelivery.id == notification_id)
    )
    notification = result.scalar_one_or_none()
    if notification is None:
        return
    notification.status = NotificationDeliveryStatus.FAILED
    notification.processing_started_at = None
    notification.last_error = error
    await db.commit()


async def try_enqueue_new_order_notifications(db: AsyncSession, order: Order) -> None:
    try:
        await enqueue_new_order_notifications(db, order)
        await db.commit()
    except SQLAlchemyError:
        await db.rollback()
        logger.exception("Could not enqueue new-order notifications for order %s", order.id)


async def try_enqueue_delivery_assigned_notification(
    db: AsyncSession,
    *,
    order: Order,
    delivery: Delivery,
    courier_user: User,
) -> None:
    try:
        await enqueue_delivery_assigned_notification(
            db,
            order=order,
            delivery=delivery,
            courier_user=courier_user,
        )
        await db.commit()
    except SQLAlchemyError:
        await db.rollback()
        logger.exception("Could not enqueue delivery assignment notification for order %s", order.id)


async def try_enqueue_courier_order_cancelled_notification(
    db: AsyncSession,
    *,
    order: Order,
    courier_users: Sequence[User],
    reason: str | None,
) -> None:
    try:
        await enqueue_courier_order_cancelled_notification(
            db,
            order=order,
            courier_users=courier_users,
            reason=reason,
        )
        await db.commit()
    except SQLAlchemyError:
        await db.rollback()
        logger.exception("Could not enqueue courier cancellation notification for order %s", order.id)


async def try_enqueue_order_status_notifications(
    db: AsyncSession,
    *,
    order: Order,
    previous_status: OrderStatus | None,
    new_status: OrderStatus,
    source: str,
    delivery: Delivery | None = None,
) -> None:
    try:
        await enqueue_order_status_notifications(
            db,
            order=order,
            previous_status=previous_status,
            new_status=new_status,
            source=source,
            delivery=delivery,
        )
        await db.commit()
    except SQLAlchemyError:
        await db.rollback()
        logger.exception("Could not enqueue order-status notifications for order %s", order.id)
