from __future__ import annotations

from decimal import Decimal

from core.time_utils import format_kyiv_datetime


ORDER_STATUS_LABELS = {
    "en": {
        "draft": "Draft",
        "placed": "Placed",
        "paid": "Paid",
        "preparing": "Preparing",
        "out_for_delivery": "Out for Delivery",
        "delivered": "Delivered",
        "cancelled": "Cancelled",
    },
    "uk": {
        "draft": "Чернетка",
        "placed": "Оформлено",
        "paid": "Оплачено",
        "preparing": "Готується",
        "out_for_delivery": "Передано в доставку",
        "delivered": "Доставлено",
        "cancelled": "Скасовано",
    },
}

DELIVERY_STATUS_LABELS = {
    "en": {
        "pending": "Pending",
        "assigned": "Assigned",
        "picked_up": "Picked Up",
        "delivered": "Delivered",
        "failed": "Failed",
    },
    "uk": {
        "pending": "Очікує",
        "assigned": "Призначено",
        "picked_up": "Забрано",
        "delivered": "Доставлено",
        "failed": "Не вдалося",
    },
}


def enum_value(value) -> str:
    if value is None:
        return ""
    return value.value if hasattr(value, "value") else str(value)


def titleize(value: str) -> str:
    return value.replace("_", " ").strip().title()


def order_status_label_for_lang(value, lang: str = "uk") -> str:
    raw = enum_value(value)
    labels = ORDER_STATUS_LABELS.get(lang, ORDER_STATUS_LABELS["en"])
    return labels.get(raw, titleize(raw))


def delivery_status_label_for_lang(value, lang: str = "uk") -> str:
    raw = enum_value(value)
    labels = DELIVERY_STATUS_LABELS.get(lang, DELIVERY_STATUS_LABELS["en"])
    return labels.get(raw, titleize(raw))


def order_status_label(value) -> str:
    return order_status_label_for_lang(value, "uk")


def delivery_status_label(value) -> str:
    return delivery_status_label_for_lang(value, "uk")


def money(value) -> str:
    amount = Decimal(str(value or 0))
    return f"{amount:.2f} UAH"


def quantity(value) -> str:
    amount = Decimal(str(value or 0)).normalize()
    text = format(amount, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def format_datetime(value) -> str:
    return format_kyiv_datetime(value)


def can_assign_order(order: dict) -> bool:
    return enum_value(order.get("status")) in {"placed", "preparing"} and not order.get("active_delivery")


def can_cancel_order(order: dict) -> bool:
    return enum_value(order.get("status")) not in {"delivered", "cancelled", "out_for_delivery"}


def can_edit_order_items(order: dict) -> bool:
    status_value = enum_value(order.get("status"))
    if status_value in {"delivered", "cancelled", "out_for_delivery"}:
        return False
    active_delivery = order.get("active_delivery") or {}
    return enum_value(active_delivery.get("status")) != "picked_up"


def has_failed_delivery(order: dict) -> bool:
    active_delivery = order.get("active_delivery") or {}
    return enum_value(active_delivery.get("status")) == "failed"
