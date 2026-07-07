from pathlib import Path
from textwrap import dedent

from telegram_export_kit.jsonl import append_jsonl
from telegram_export_kit.verify import verify_export


def test_verify_accepts_complete_export(tmp_path: Path) -> None:
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "a.jpg").write_text("image")
    _write_valid_manifest(tmp_path)
    append_jsonl(
        tmp_path / "messages.jsonl",
        {
            "id": 1,
            "date": "2026-01-01T00:00:00+00:00",
            "chat": {"id": 100},
            "context_kind": "target",
            "media": [{"kind": "photo", "path": "assets/a.jpg"}],
        },
    )

    result = verify_export(tmp_path)

    assert result.ok
    assert result.message_count == 1
    assert result.asset_count == 1
    assert result.issues == []


def test_verify_reports_duplicate_ids_and_missing_assets(tmp_path: Path) -> None:
    _write_valid_manifest(tmp_path)
    for text in ["first", "second"]:
        append_jsonl(
            tmp_path / "messages.jsonl",
            {
                "id": 1,
                "date": "2026-01-01T00:00:00+00:00",
                "chat": {"id": 100},
                "context_kind": "target",
                "text": text,
                "media": [{"kind": "photo", "path": "assets/missing.jpg"}],
            },
        )

    result = verify_export(tmp_path / "messages.jsonl")
    codes = [issue.code for issue in result.issues]

    assert not result.ok
    assert "duplicate_id" in codes
    assert "missing_asset" in codes


def test_verify_warns_for_missing_manifest_and_reply_target(tmp_path: Path) -> None:
    append_jsonl(
        tmp_path / "messages.jsonl",
        {
            "id": 1,
            "date": "2026-01-01T00:00:00+00:00",
            "chat": {"id": 100},
            "context_kind": "target",
            "reply_to_msg_id": 99,
        },
    )

    result = verify_export(tmp_path)
    codes = [issue.code for issue in result.issues]

    assert result.ok
    assert "missing_manifest" in codes
    assert "missing_reply" in codes


def test_verify_reports_invalid_jsonl(tmp_path: Path) -> None:
    (tmp_path / "messages.jsonl").write_text("{bad json}\n", encoding="utf-8")

    result = verify_export(tmp_path)

    assert not result.ok
    assert result.issues[0].code == "invalid_json"


def test_verify_reports_manifest_contract_errors(tmp_path: Path) -> None:
    (tmp_path / "manifest.json").write_text(
        '{"export_version": 1, "messages_path": "custom.jsonl", "runs": []}',
        encoding="utf-8",
    )
    append_jsonl(
        tmp_path / "messages.jsonl",
        {
            "id": 1,
            "date": "2026-01-01T00:00:00+00:00",
            "chat": {"id": 100},
            "context_kind": "target",
        },
    )

    result = verify_export(tmp_path)
    codes = [issue.code for issue in result.issues]

    assert not result.ok
    assert codes.count("manifest_missing_field") == 4
    assert "manifest_invalid_runs" in codes
    assert "manifest_invalid_messages_path" in codes
    assert "manifest_invalid_mode" in codes
    assert "manifest_invalid_chat" in codes
    assert "manifest_invalid_stats" in codes


def test_verify_reports_manifest_stats_and_run_errors(tmp_path: Path) -> None:
    (tmp_path / "manifest.json").write_text(
        dedent(
            """
            {
              "export_version": 1,
              "id": "abc12345",
              "uuid": "abc12345-0000-4000-8000-000000000000",
              "path_key": "path-key",
              "criteria_hash": "criteria-hash",
              "messages_path": "messages.jsonl",
              "mode": "group_slice",
              "chat": {"id": 100},
              "stats": {"selected": 2},
              "runs": [{"ran_at": "not-a-date"}]
            }
            """
        ),
        encoding="utf-8",
    )
    append_jsonl(
        tmp_path / "messages.jsonl",
        {
            "id": 1,
            "date": "2026-01-01T00:00:00+00:00",
            "chat": {"id": 100},
            "context_kind": "target",
        },
    )

    result = verify_export(tmp_path)
    codes = [issue.code for issue in result.issues]

    assert not result.ok
    assert "manifest_stats_mismatch" in codes
    assert "manifest_invalid_run" in codes


def _write_valid_manifest(root: Path) -> None:
    (root / "manifest.json").write_text(
        dedent(
            """
            {
              "export_version": 1,
              "id": "abc12345",
              "uuid": "abc12345-0000-4000-8000-000000000000",
              "path_key": "path-key",
              "criteria_hash": "criteria-hash",
              "messages_path": "messages.jsonl",
              "mode": "private",
              "chat": {"id": 100},
              "stats": {"selected": 1},
              "runs": [
                {
                  "ran_at": "2026-01-01T00:00:00+00:00",
                  "stats": {}
                }
              ]
            }
            """
        ),
        encoding="utf-8",
    )
