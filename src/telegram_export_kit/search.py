from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, tzinfo
from pathlib import Path
from typing import Any, Literal

from telegram_export_kit.jsonl import read_jsonl
from telegram_export_kit.utils import parse_datetime, resolve_timezone

SearchContext = Literal["private", "target", "before", "after"]


@dataclass(frozen=True)
class SearchResult:
    id: int
    date: str
    sender: str
    context_kind: str
    media_count: int
    snippet: str
    anchor: str
    record: dict[str, Any]


def search_messages(
    input_path: Path,
    *,
    query: str | None = None,
    sender: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    context: SearchContext | None = None,
    target_only: bool = False,
    has_media: bool = False,
    limit: int | None = None,
    timezone: str | None = None,
) -> list[SearchResult]:
    messages_path = resolve_messages_path(input_path)
    display_timezone = resolve_timezone(timezone or _manifest_timezone(messages_path))
    since = parse_datetime(date_from, timezone=display_timezone)
    until = parse_datetime(date_to, next_day=True, timezone=display_timezone)
    normalized_query = query.casefold() if query else None
    normalized_sender = sender.casefold() if sender else None
    results: list[SearchResult] = []

    for record in read_jsonl(messages_path):
        date = _record_datetime(record)
        if since is not None and (date is None or date < since):
            continue
        if until is not None and (date is None or date >= until):
            continue
        if context is not None and record.get("context_kind") != context:
            continue
        if target_only and not _is_target_match(record):
            continue
        if has_media and _media_count(record) == 0:
            continue
        if normalized_sender is not None and not _sender_matches(record, normalized_sender):
            continue
        if normalized_query is not None and normalized_query not in _text(record).casefold():
            continue

        results.append(_result(record, query=query, timezone=display_timezone))
        if limit is not None and len(results) >= limit:
            break

    return results


def resolve_messages_path(path: Path) -> Path:
    return path / "messages.jsonl" if path.is_dir() else path


def _manifest_timezone(input_path: Path) -> str | None:
    manifest_path = input_path.with_name("manifest.json")
    if not manifest_path.exists():
        return None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    timezone = manifest.get("timezone")
    return timezone if isinstance(timezone, str) and timezone else None


def _record_datetime(record: dict[str, Any]) -> datetime | None:
    raw_date = record.get("date")
    if not isinstance(raw_date, str) or not raw_date:
        return None
    try:
        parsed = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.astimezone()
    return parsed


def _result(
    record: dict[str, Any],
    *,
    query: str | None,
    timezone: tzinfo,
) -> SearchResult:
    message_id = _message_id(record)
    date = _format_date(record, timezone=timezone)
    sender = _sender_label(record)
    context_kind = str(record.get("context_kind") or "")
    media_count = _media_count(record)
    return SearchResult(
        id=message_id,
        date=date,
        sender=sender,
        context_kind=context_kind,
        media_count=media_count,
        snippet=_snippet(_text(record), query=query),
        anchor=f"messages.html#msg-{message_id}",
        record=record,
    )


def _message_id(record: dict[str, Any]) -> int:
    raw_id = record.get("id")
    return raw_id if isinstance(raw_id, int) else 0


def _format_date(record: dict[str, Any], *, timezone: tzinfo) -> str:
    date = _record_datetime(record)
    if date is None:
        raw_date = record.get("date")
        return raw_date if isinstance(raw_date, str) else ""
    return date.astimezone(timezone).strftime("%Y-%m-%d %H:%M:%S")


def _sender_matches(record: dict[str, Any], normalized_sender: str) -> bool:
    sender = record.get("sender")
    if not isinstance(sender, dict):
        return False
    values = [
        sender.get("id"),
        sender.get("username"),
        sender.get("display_name"),
        sender.get("first_name"),
        sender.get("last_name"),
    ]
    return any(normalized_sender in str(value).casefold() for value in values if value is not None)


def _is_target_match(record: dict[str, Any]) -> bool:
    return bool(record.get("sender_match") or record.get("target_user_match"))


def _sender_label(record: dict[str, Any]) -> str:
    sender = record.get("sender")
    if not isinstance(sender, dict):
        return "unknown"
    value = sender.get("display_name") or sender.get("username") or sender.get("id")
    return str(value) if value is not None else "unknown"


def _text(record: dict[str, Any]) -> str:
    text = record.get("text")
    return text if isinstance(text, str) else ""


def _media_count(record: dict[str, Any]) -> int:
    media = record.get("media")
    return len(media) if isinstance(media, list) else 0


def _snippet(text: str, *, query: str | None, limit: int = 120) -> str:
    collapsed = " ".join(text.split())
    if not collapsed:
        return ""
    if query:
        index = collapsed.casefold().find(query.casefold())
        if index >= 0:
            start = max(0, index - 40)
            end = min(len(collapsed), index + len(query) + 80)
            prefix = "..." if start > 0 else ""
            suffix = "..." if end < len(collapsed) else ""
            return f"{prefix}{collapsed[start:end]}{suffix}"
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 3].rstrip() + "..."
