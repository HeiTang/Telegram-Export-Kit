from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from telegram_export_kit.utils import parse_datetime, resolve_timezone


def test_parse_datetime_with_explicit_timezone() -> None:
    assert parse_datetime("2026-01-01T08:30:00+08:00") == datetime(
        2026,
        1,
        1,
        0,
        30,
        tzinfo=UTC,
    )


def test_parse_date_only_next_day_returns_exclusive_upper_bound() -> None:
    start = parse_datetime("2026-01-01", timezone=ZoneInfo("Asia/Taipei"))
    end = parse_datetime("2026-01-01", next_day=True, timezone=ZoneInfo("Asia/Taipei"))

    assert start is not None
    assert end is not None
    assert end > start
    assert start == datetime(2025, 12, 31, 16, 0, tzinfo=UTC)
    assert end == datetime(2026, 1, 1, 16, 0, tzinfo=UTC)


def test_resolve_timezone_accepts_utc_offset() -> None:
    utc_plus_8 = resolve_timezone("UTC+8").utcoffset(None)
    plus_0800 = resolve_timezone("+08:00").utcoffset(None)

    assert utc_plus_8 is not None
    assert plus_0800 is not None
    assert utc_plus_8.total_seconds() == 28800
    assert plus_0800.total_seconds() == 28800
