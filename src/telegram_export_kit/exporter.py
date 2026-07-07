from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from telegram_export_kit.gateway import TelegramGateway
from telegram_export_kit.jsonl import append_jsonl
from telegram_export_kit.manifest_writer import write_export_manifest
from telegram_export_kit.media_exporter import (
    existing_messages,
    media_needs_update,
    merge_media,
    replace_message_record,
)
from telegram_export_kit.message_selector import select_messages
from telegram_export_kit.models import ExportOptions

ProgressCallback = Callable[[str, Mapping[str, object]], None]


@dataclass(frozen=True)
class ExportResult:
    out_dir: Path
    total_seen: int
    selected: int
    written: int
    media_updated: int
    skipped_existing: int
    target_messages: int
    dry_run: bool


def _emit(
    progress: ProgressCallback | None,
    event: str,
    payload: Mapping[str, object],
) -> None:
    if progress is not None:
        progress(event, payload)


async def export_chat(
    gateway: TelegramGateway,
    options: ExportOptions,
    *,
    progress: ProgressCallback | None = None,
) -> ExportResult:
    chat = await gateway.resolve_chat(options.chat)
    chat_record = gateway.chat_record(chat)
    is_private = gateway.is_private_chat(chat)

    if options.sender is not None:
        target_sender = await gateway.resolve_user(options.sender)
        target_record = gateway.sender_record(target_sender)
        target_sender_id: int | None = gateway.entity_id(target_sender)
    elif is_private:
        target_sender = chat
        target_record = gateway.sender_record(target_sender)
        target_sender_id = gateway.entity_id(target_sender)
    else:
        target_record = None
        target_sender_id = None

    _emit(progress, "scan_start", {"chat": chat_record.title or chat_record.id})

    messages = []
    async for message in gateway.iter_messages(chat, since=options.since, until=options.until):
        messages.append(message)
        if len(messages) == 1 or len(messages) % 500 == 0:
            _emit(progress, "scan", {"seen": len(messages)})

    messages.sort(key=gateway.message_sort_key)

    selection = select_messages(
        messages,
        is_private=is_private,
        target_sender_id=target_sender_id,
        sender_id_for=gateway.message_sender_id,
        window_before=options.window_before,
        window_after=options.window_after,
    )

    messages_path = options.out_dir / "messages.jsonl"
    assets_dir = options.out_dir / "assets"
    previous_messages = existing_messages(messages_path) if options.resume else {}
    existing_ids = set(previous_messages)
    selected_total = selection.selected_count

    _emit(
        progress,
        "selected",
        {
            "seen": len(messages),
            "selected": selected_total,
            "target_messages": selection.target_count,
            "existing": len(existing_ids),
        },
    )

    written = 0
    media_updated = 0
    skipped_existing = 0
    if not options.dry_run:
        options.out_dir.mkdir(parents=True, exist_ok=True)
        assets_dir.mkdir(parents=True, exist_ok=True)

    for position, index in enumerate(sorted(selection.selected_indexes), start=1):
        message = messages[index]
        message_id = cast(Any, message).id
        if message_id in existing_ids:
            existing_record = previous_messages[message_id]
            if (
                options.download_media
                and options.update_media
                and not options.dry_run
                and media_needs_update(existing_record)
            ):
                _emit(
                    progress,
                    "write_start",
                    {"position": position, "total": selected_total, "message_id": message_id},
                )
                media = await gateway.download_media(message, assets_dir=assets_dir)
                if media:
                    replace_message_record(
                        messages_path,
                        message_id,
                        merge_media(existing_record, media),
                    )
                    media_updated += 1
                    _emit(
                        progress,
                        "media_updated",
                        {
                            "position": position,
                            "total": selected_total,
                            "message_id": message_id,
                            "media_updated": media_updated,
                        },
                    )
                    continue

            skipped_existing += 1
            _emit(
                progress,
                "skip_existing",
                {
                    "position": position,
                    "total": selected_total,
                    "message_id": message_id,
                    "skipped_existing": skipped_existing,
                },
            )
            continue

        if options.dry_run:
            _emit(
                progress,
                "dry_run_selected",
                {
                    "position": position,
                    "total": selected_total,
                    "message_id": message_id,
                },
            )
            continue

        _emit(
            progress,
            "write_start",
            {"position": position, "total": selected_total, "message_id": message_id},
        )
        record = await gateway.build_message_record(
            message,
            chat=chat,
            context_kind=selection.context_by_index[index],
            target_sender_id=target_sender_id,
            assets_dir=assets_dir,
            download_media=options.download_media,
        )
        append_jsonl(messages_path, record)
        written += 1
        _emit(
            progress,
            "written",
            {
                "position": position,
                "total": selected_total,
                "message_id": message_id,
                "written": written,
            },
        )

    stats = {
        "total_seen": len(messages),
        "selected": selection.selected_count,
        "written": written,
        "media_updated": media_updated,
        "skipped_existing": skipped_existing,
        "target_messages": selection.target_count,
    }

    if not options.dry_run:
        write_export_manifest(
            options.out_dir / "manifest.json",
            options=options,
            chat_record=chat_record,
            target_record=target_record,
            mode=selection.mode,
            stats=stats,
        )

    _emit(progress, "complete", stats)

    return ExportResult(
        out_dir=options.out_dir,
        total_seen=len(messages),
        selected=selection.selected_count,
        written=written,
        media_updated=media_updated,
        skipped_existing=skipped_existing,
        target_messages=selection.target_count,
        dry_run=options.dry_run,
    )
