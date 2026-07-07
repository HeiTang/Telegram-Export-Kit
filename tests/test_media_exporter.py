from __future__ import annotations

from pathlib import Path

from telegram_export_kit.jsonl import append_jsonl, read_jsonl
from telegram_export_kit.media_exporter import (
    existing_messages,
    media_needs_update,
    merge_media,
    replace_message_record,
)
from telegram_export_kit.models import MediaRecord


def test_media_needs_update_only_when_media_is_missing_or_skipped() -> None:
    skipped_media = {"media": [{"kind": "photo", "skipped_reason": "no_media"}]}
    downloaded_media = {"media": [{"kind": "photo", "path": "assets/1.jpg"}]}

    assert media_needs_update({})
    assert media_needs_update({"media": []})
    assert media_needs_update(skipped_media)
    assert not media_needs_update(downloaded_media)


def test_replace_message_record_preserves_other_rows(tmp_path: Path) -> None:
    path = tmp_path / "messages.jsonl"
    append_jsonl(path, {"id": 1, "text": "a", "media": []})
    append_jsonl(path, {"id": 2, "text": "b", "media": []})

    replacement = merge_media(
        existing_messages(path)[1],
        [MediaRecord(kind="photo", path="assets/1.jpg", file_name="1.jpg")],
    )
    replace_message_record(path, 1, replacement)

    rows = list(read_jsonl(path))
    assert rows == [
        {
            "id": 1,
            "text": "a",
            "media": [{"kind": "photo", "path": "assets/1.jpg", "file_name": "1.jpg"}],
        },
        {"id": 2, "text": "b", "media": []},
    ]
