"""UTC query bounds for the Shanghai operations dashboard."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

SHANGHAI = ZoneInfo("Asia/Shanghai")


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def calendar_window(now: datetime, days: int) -> tuple[datetime, datetime]:
    """Exactly `days` Shanghai calendar dates including today, as naive UTC."""
    local = now.replace(tzinfo=timezone.utc).astimezone(SHANGHAI)
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
    start = midnight - timedelta(days=days - 1)
    end = midnight + timedelta(days=1)
    return tuple(value.astimezone(timezone.utc).replace(tzinfo=None) for value in (start, end))


def is_return_visit(registered_at: datetime, sent_at: datetime) -> bool:
    """Registration-relative days 2–7: [24 hours, 168 hours)."""
    return registered_at + timedelta(days=1) <= sent_at < registered_at + timedelta(days=7)
