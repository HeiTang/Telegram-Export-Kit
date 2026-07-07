from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from telegram_export_kit.export_index import (
    ExportEntry,
    build_criteria_hash,
    build_path_key,
    existing_export_ids,
    find_export_by_criteria,
    find_exports_by_path_key,
    generate_export_identity,
)
from telegram_export_kit.models import ChatRecord, SenderRecord
from telegram_export_kit.utils import safe_filename

ExportMode = Literal["private", "group_slice", "full_chat"]


class ExportPlanError(RuntimeError):
    pass


class ExistingExportError(ExportPlanError):
    def __init__(self, entry: ExportEntry) -> None:
        super().__init__(f"Export already exists: {entry.id} {entry.root_dir}")
        self.entry = entry


class PathCollisionError(ExportPlanError):
    def __init__(self, entries: list[ExportEntry]) -> None:
        ids = ", ".join(entry.id for entry in entries)
        super().__init__(f"Same scope but different criteria: {ids}")
        self.entries = entries


@dataclass(frozen=True)
class ExportPlan:
    export_id: str
    export_uuid: str
    out_dir: Path
    resume: bool
    should_reset: bool
    mode: ExportMode
    source: dict[str, Any]
    path_key: str
    criteria_hash: str
    chat_label: str
    target_label: str
    scope: str


def plan_export(
    *,
    out: Path,
    chat_ref: str,
    sender_ref: str | None,
    chat_record: ChatRecord,
    target_record: SenderRecord | None,
    date_label: str,
    date: str | None,
    start_date: str | None,
    end_date: str | None,
    since: datetime | None,
    until: datetime | None,
    timezone: str,
    window_before: int,
    window_after: int,
    flat: bool,
    update: bool,
    overwrite: bool,
    new: bool,
    dry_run: bool,
    resume: bool,
) -> ExportPlan:
    mode = resolve_export_mode(chat_type=chat_record.type, target_record=target_record)
    target_id = target_record.id if target_record is not None else None
    path_key = build_path_key(
        chat_id=chat_record.id,
        target_id=target_id,
        date_scope=date_label,
    )
    criteria_hash = build_criteria_hash(
        chat_id=chat_record.id,
        target_id=target_id,
        mode=mode,
        since=since,
        until=until,
        window_before=window_before,
        window_after=window_after,
    )
    export_id, export_uuid = generate_export_identity(existing_export_ids(out))
    out_dir = default_export_dir(
        out=out,
        chat_record=chat_record,
        target_record=target_record,
        date_label=date_label,
        flat=flat,
    )
    should_reset = False

    existing = find_export_by_criteria(out, criteria_hash)
    if existing is not None and not new:
        if not update and not overwrite and not dry_run:
            raise ExistingExportError(existing)
        export_id = existing.id
        export_uuid = existing.uuid
        out_dir = existing.root_dir
        resume = True
        should_reset = overwrite and not dry_run
        if should_reset:
            resume = False
    elif not new:
        collisions = find_exports_by_path_key(out, path_key)
        if collisions and not dry_run:
            raise PathCollisionError(collisions)
    else:
        out_dir = unique_export_dir(out_dir, export_id)

    return ExportPlan(
        export_id=export_id,
        export_uuid=export_uuid,
        out_dir=out_dir,
        resume=resume,
        should_reset=should_reset,
        mode=mode,
        source=source_payload(
            chat_ref=chat_ref,
            chat_id=chat_record.id,
            sender_ref=sender_ref,
            sender_id=target_id,
            date=date,
            start_date=start_date,
            end_date=end_date,
            since=since,
            until=until,
            timezone=timezone,
        ),
        path_key=path_key,
        criteria_hash=criteria_hash,
        chat_label=chat_label(chat_record),
        target_label=target_label(target_record),
        scope=date_label,
    )


def resolve_export_mode(
    *,
    chat_type: str,
    target_record: SenderRecord | None,
) -> ExportMode:
    if chat_type == "private":
        return "private"
    if target_record is None:
        return "full_chat"
    return "group_slice"


def default_export_dir(
    *,
    out: Path,
    chat_record: ChatRecord,
    target_record: SenderRecord | None,
    date_label: str,
    flat: bool,
) -> Path:
    if flat:
        return out
    subject = export_scope_key(chat_record=chat_record, target_record=target_record)
    return out / subject / safe_filename(date_label, fallback="all")


def export_scope_key(*, chat_record: ChatRecord, target_record: SenderRecord | None) -> str:
    if chat_record.type == "private":
        return f"private__u{chat_record.id}"
    if target_record is None:
        return f"group__c{chat_record.id}__all"
    if target_record.id is None:
        raise ValueError("target sender id is required for stable export path")
    return f"group__c{chat_record.id}__u{target_record.id}"


def chat_label(record: ChatRecord) -> str:
    return record.title or record.username or str(record.id)


def target_label(record: SenderRecord | None) -> str:
    if record is None:
        return "all-senders"
    return record.display_name or record.username or str(record.id)


def unique_export_dir(base: Path, export_id: str) -> Path:
    candidate = base.with_name(f"{base.name}__{export_id}")
    if not candidate.exists():
        return candidate
    counter = 2
    while True:
        numbered = base.with_name(f"{base.name}__{export_id}_{counter}")
        if not numbered.exists():
            return numbered
        counter += 1


def reset_export_payload(out_dir: Path) -> None:
    for name in ["messages.jsonl", "manifest.json"]:
        path = out_dir / name
        if path.exists():
            path.unlink()
    assets_dir = out_dir / "assets"
    if assets_dir.exists():
        shutil.rmtree(assets_dir)


def source_payload(
    *,
    chat_ref: str,
    chat_id: int,
    sender_ref: str | None,
    sender_id: int | None,
    date: str | None,
    start_date: str | None,
    end_date: str | None,
    since: datetime | None,
    until: datetime | None,
    timezone: str,
) -> dict[str, Any]:
    if date is not None:
        date_mode = "date"
    elif start_date is not None and end_date is not None:
        date_mode = "range"
    else:
        date_mode = "all"
    return {
        "chat_ref": chat_ref,
        "chat_id": chat_id,
        "sender_ref": sender_ref,
        "sender_id": sender_id,
        "date_mode": date_mode,
        "date": date,
        "start_date": start_date,
        "end_date": end_date,
        "since": datetime_json(since),
        "until": datetime_json(until),
        "timezone": timezone,
    }


def datetime_json(value: datetime | None) -> str | None:
    if value is None:
        return None
    parsed = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")
