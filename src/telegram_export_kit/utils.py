from __future__ import annotations

import os
import re
from datetime import UTC, datetime, time, timedelta, timezone, tzinfo
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

_UNSAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")
_DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_UTC_OFFSET = re.compile(r"^(?:UTC)?([+-])(\d{1,2})(?::?(\d{2}))?$", re.IGNORECASE)


def safe_filename(value: str, *, fallback: str = "file") -> str:
    cleaned = _UNSAFE_FILENAME.sub("_", value).strip("._")
    return cleaned or fallback


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path

    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    index = 2
    while True:
        candidate = parent / f"{stem}_{index}{suffix}"
        if not candidate.exists():
            return candidate
        index += 1


def resolve_timezone(value: str | None = None) -> tzinfo:
    timezone_name = value or os.getenv("TG_TIMEZONE")
    if timezone_name:
        offset = _parse_utc_offset(timezone_name)
        if offset is not None:
            return offset
        try:
            return ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"Unknown timezone: {timezone_name}") from exc
    return datetime.now().astimezone().tzinfo or UTC


def _parse_utc_offset(value: str) -> timezone | None:
    if value.upper() == "UTC":
        return UTC
    match = _UTC_OFFSET.match(value.strip())
    if not match:
        return None
    sign, raw_hours, raw_minutes = match.groups()
    hours = int(raw_hours)
    minutes = int(raw_minutes or "0")
    if hours > 23 or minutes > 59:
        raise ValueError(f"Invalid UTC offset: {value}")
    delta = timedelta(hours=hours, minutes=minutes)
    if sign == "-":
        delta = -delta
    return timezone(delta, name=f"UTC{sign}{hours:02d}:{minutes:02d}")


def parse_datetime(
    value: str | None,
    *,
    next_day: bool = False,
    timezone: tzinfo | None = None,
) -> datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    resolved_timezone = timezone or resolve_timezone()
    if _DATE_ONLY.match(normalized):
        parsed_date = datetime.fromisoformat(normalized).date()
        if next_day:
            parsed_date += timedelta(days=1)
        parsed = datetime.combine(parsed_date, time.min)
    else:
        parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=resolved_timezone).astimezone(UTC)
    return parsed.astimezone(UTC)


def ensure_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
