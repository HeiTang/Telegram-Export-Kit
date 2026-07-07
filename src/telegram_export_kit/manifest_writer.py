from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from telegram_export_kit.jsonl import write_json
from telegram_export_kit.message_selector import ExportMode
from telegram_export_kit.models import ChatRecord, ExportManifest, ExportOptions, SenderRecord


def read_manifest(path: Path) -> ExportManifest | None:
    if not path.exists():
        return None
    return ExportManifest.model_validate(json.loads(path.read_text(encoding="utf-8")))


def write_export_manifest(
    path: Path,
    *,
    options: ExportOptions,
    chat_record: ChatRecord,
    target_record: SenderRecord | None,
    mode: ExportMode,
    stats: dict[str, int],
) -> ExportManifest:
    previous_manifest = read_manifest(path)
    now = datetime.now(UTC)
    run = {
        "ran_at": now.isoformat(),
        "download_media": options.download_media,
        "update_media": options.update_media,
        "timezone": options.timezone,
        "stats": stats,
    }
    manifest = ExportManifest(
        id=options.export_id or (previous_manifest.id if previous_manifest else None),
        uuid=options.export_uuid or (previous_manifest.uuid if previous_manifest else None),
        created_at=previous_manifest.created_at if previous_manifest else now,
        updated_at=now,
        chat=chat_record,
        target_sender=target_record,
        mode=mode,
        since=options.since,
        until=options.until,
        timezone=options.timezone,
        window_before=options.window_before,
        window_after=options.window_after,
        download_media=options.download_media,
        source=options.source,
        path_key=options.path_key,
        criteria_hash=options.criteria_hash,
        stats=stats,
        runs=[*(previous_manifest.runs if previous_manifest else []), run],
    )
    write_json(path, manifest)
    return manifest
