from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo


UTC = timezone.utc
KYIV_TZ = ZoneInfo("Europe/Kyiv")


def ensure_utc_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def parse_datetime(value: object | None) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return ensure_utc_datetime(value)
    text = str(value)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return ensure_utc_datetime(datetime.fromisoformat(text))
    except ValueError:
        return None


def to_kyiv_datetime(value: object | None) -> datetime | None:
    parsed = parse_datetime(value)
    if parsed is None:
        return None
    return parsed.astimezone(KYIV_TZ)


def format_kyiv_datetime(value: object | None, *, default: str = "-") -> str:
    kyiv_value = to_kyiv_datetime(value)
    if kyiv_value is None:
        return default if value in (None, "") else str(value)
    return kyiv_value.strftime("%d.%m.%Y %H:%M")


def kyiv_today() -> date:
    return datetime.now(KYIV_TZ).date()


def local_day_range_utc(*, newest_days_ago: int, oldest_days_ago: int) -> tuple[datetime, datetime]:
    if newest_days_ago < 0 or oldest_days_ago < 0:
        raise ValueError("Day offsets must be non-negative")

    start_offset = max(newest_days_ago, oldest_days_ago)
    end_offset = min(newest_days_ago, oldest_days_ago)
    today = kyiv_today()
    start_date = today - timedelta(days=start_offset)
    end_date = today - timedelta(days=end_offset) + timedelta(days=1)

    start_local = datetime.combine(start_date, time.min, tzinfo=KYIV_TZ)
    end_local = datetime.combine(end_date, time.min, tzinfo=KYIV_TZ)
    return start_local.astimezone(UTC), end_local.astimezone(UTC)
