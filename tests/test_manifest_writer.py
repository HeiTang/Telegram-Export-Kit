from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from telegram_export_kit.jsonl import write_json
from telegram_export_kit.manifest_writer import read_manifest, write_export_manifest
from telegram_export_kit.models import ChatRecord, ExportOptions, SenderRecord


def test_write_export_manifest_creates_identity_and_run_history(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    chat_record = ChatRecord(id=100, title="Group", username="group", type="group")
    target_record = SenderRecord(id=7, username="target", display_name="Target")

    manifest = write_export_manifest(
        manifest_path,
        options=ExportOptions(
            chat="group",
            sender="target",
            out_dir=tmp_path,
            since=datetime(2026, 1, 1, tzinfo=UTC),
            until=datetime(2026, 1, 2, tzinfo=UTC),
            timezone="Asia/Taipei",
            window_before=3,
            window_after=4,
            download_media=False,
            export_id="abc12345",
            export_uuid="abc12345-0000-4000-8000-000000000000",
            source={"chat_ref": "group"},
            path_key="path-key",
            criteria_hash="criteria-hash",
        ),
        chat_record=chat_record,
        target_record=target_record,
        mode="group_slice",
        stats={"selected": 2, "written": 2},
    )

    assert manifest.id == "abc12345"
    assert manifest.uuid == "abc12345-0000-4000-8000-000000000000"
    assert manifest.chat == chat_record
    assert manifest.target_sender == target_record
    assert manifest.mode == "group_slice"
    assert manifest.path_key == "path-key"
    assert manifest.criteria_hash == "criteria-hash"
    assert manifest.messages_path == "messages.jsonl"
    assert manifest.runs == [
        {
            "ran_at": manifest.runs[0]["ran_at"],
            "download_media": False,
            "update_media": True,
            "timezone": "Asia/Taipei",
            "stats": {"selected": 2, "written": 2},
        }
    ]

    persisted = read_manifest(manifest_path)
    assert persisted == manifest


def test_write_export_manifest_preserves_existing_identity_and_appends_runs(
    tmp_path: Path,
) -> None:
    manifest_path = tmp_path / "manifest.json"
    chat_record = ChatRecord(id=100, title="Group", username="group", type="group")

    first = write_export_manifest(
        manifest_path,
        options=ExportOptions(
            chat="group",
            out_dir=tmp_path,
            export_id="abc12345",
            export_uuid="abc12345-0000-4000-8000-000000000000",
            path_key="path-key",
            criteria_hash="criteria-hash",
        ),
        chat_record=chat_record,
        target_record=None,
        mode="full_chat",
        stats={"selected": 1, "written": 1},
    )

    second = write_export_manifest(
        manifest_path,
        options=ExportOptions(
            chat="group",
            out_dir=tmp_path,
            path_key="new-path-key",
            criteria_hash="new-criteria-hash",
        ),
        chat_record=chat_record,
        target_record=None,
        mode="full_chat",
        stats={"selected": 1, "written": 0, "skipped_existing": 1},
    )

    assert second.id == first.id
    assert second.uuid == first.uuid
    assert second.created_at == first.created_at
    assert second.updated_at >= first.updated_at
    assert second.path_key == "new-path-key"
    assert second.criteria_hash == "new-criteria-hash"
    assert len(second.runs) == 2
    assert second.runs[0]["stats"] == {"selected": 1, "written": 1}
    assert second.runs[1]["stats"] == {
        "selected": 1,
        "written": 0,
        "skipped_existing": 1,
    }


def test_failed_json_serialization_preserves_existing_manifest(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    path.write_text('{"original":true}')
    with pytest.raises(TypeError):
        write_json(path, object())
    assert path.read_text() == '{"original":true}'
