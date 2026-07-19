"""Application-wide handling for UTC persistence and China-facing time values."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo


UTC = timezone.utc
SHANGHAI_TIME_ZONE = ZoneInfo("Asia/Shanghai")


def utcnow() -> datetime:
    """Return the current instant as the naive UTC value used by database columns."""
    return datetime.now(UTC).replace(tzinfo=None)


def to_shanghai(value: datetime) -> datetime:
    """Convert a persisted UTC value to an offset-aware Asia/Shanghai value.

    Existing database timestamps are naive UTC values. Naive inputs are therefore
    deliberately interpreted as UTC before being converted for external output.
    """
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(SHANGHAI_TIME_ZONE)


def serialize_shanghai(value: datetime) -> str:
    """Serialize a datetime for public API responses in China Standard Time."""
    return to_shanghai(value).isoformat()
