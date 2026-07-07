from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from telegram_export_kit.jsonl import read_jsonl, write_jsonl
from telegram_export_kit.models import MediaRecord


def existing_messages(path: Path) -> dict[int, dict[str, Any]]:
    if not path.exists():
        return {}
    messages: dict[int, dict[str, Any]] = {}
    for item in read_jsonl(path):
        raw_id = item.get("id")
        if isinstance(raw_id, int):
            messages[raw_id] = item
    return messages


def media_needs_update(record: Mapping[str, Any]) -> bool:
    media = record.get("media")
    if not media:
        return True
    if not isinstance(media, list):
        return True
    return all(isinstance(item, Mapping) and item.get("skipped_reason") for item in media)


def merge_media(record: dict[str, Any], media: list[MediaRecord]) -> dict[str, Any]:
    merged = dict(record)
    merged["media"] = [item.model_dump(mode="json", exclude_none=True) for item in media]
    return merged


def replace_message_record(path: Path, message_id: int, record: dict[str, Any]) -> None:
    rows = [item if item.get("id") != message_id else record for item in read_jsonl(path)]
    write_jsonl(path, rows)
