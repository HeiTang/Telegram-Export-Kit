import json
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
import typer
from typer.testing import CliRunner

from telegram_export_kit import cli
from telegram_export_kit.cli import _resolve_time_range, app
from telegram_export_kit.export_index import ExportEntry
from telegram_export_kit.export_plan import ExistingExportError, ExportPlan, default_export_dir
from telegram_export_kit.exporter import ExportResult
from telegram_export_kit.jsonl import append_jsonl
from telegram_export_kit.models import ChatRecord, ExportOptions, SenderRecord

runner = CliRunner()


def test_resolve_single_date_range() -> None:
    since, until = _resolve_time_range(
        date="2026-01-31",
        start_date=None,
        end_date=None,
        timezone=ZoneInfo("Asia/Taipei"),
    )[:2]

    assert since is not None
    assert until is not None
    assert since < until
    assert since.isoformat() == "2026-01-30T16:00:00+00:00"
    assert until.isoformat() == "2026-01-31T16:00:00+00:00"


def test_resolve_date_from_range() -> None:
    since, until, label = _resolve_time_range(
        date=None,
        start_date="2026-01-01",
        end_date="2026-01-31",
        timezone=ZoneInfo("Asia/Taipei"),
    )

    assert since is not None
    assert until is not None
    assert since < until
    assert since.isoformat() == "2025-12-31T16:00:00+00:00"
    assert until.isoformat() == "2026-01-31T16:00:00+00:00"
    assert label == "2026-01-01_to_2026-01-31"


def test_resolve_date_range_requires_both_bounds() -> None:
    with pytest.raises(typer.BadParameter):
        _resolve_time_range(
            date=None,
            start_date="2026-01-01",
            end_date=None,
            timezone=ZoneInfo("Asia/Taipei"),
        )


def test_resolve_rejects_mixed_modes() -> None:
    with pytest.raises(typer.BadParameter):
        _resolve_time_range(
            date="2026-01-31",
            start_date="2026-01-01",
            end_date="2026-01-31",
            timezone=ZoneInfo("Asia/Taipei"),
        )


def test_default_export_dir_partitions_by_stable_ids_and_date() -> None:
    assert default_export_dir(
        out=Path("exports"),
        chat_record=ChatRecord(id=-100123, title="Group Chat", username="group_chat", type="group"),
        target_record=SenderRecord(id=7, username="alice", display_name="Alice"),
        date_label="2026-01-01_to_2026-01-31",
        flat=False,
    ) == Path("exports/group__c-100123__u7/2026-01-01_to_2026-01-31")


def test_default_export_dir_flat_keeps_exact_out() -> None:
    assert default_export_dir(
        out=Path("exports/custom"),
        chat_record=ChatRecord(id=1, title="chat", type="group"),
        target_record=None,
        date_label="all",
        flat=True,
    ) == Path("exports/custom")


def test_export_command_passes_action_flags_to_plan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_plan: dict[str, object] = {}
    captured_options: dict[str, object] = {}
    captured_upsert: dict[str, object] = {}

    _install_export_command_fakes(
        monkeypatch,
        captured_plan=captured_plan,
        captured_options=captured_options,
        captured_upsert=captured_upsert,
    )

    result = runner.invoke(
        app,
        [
            "export",
            "--chat",
            "group",
            "--sender",
            "target",
            "--date",
            "2026-01-01",
            "--window-before",
            "3",
            "--window-after",
            "4",
            "--no-media",
            "--update",
            "--out",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0, result.output
    assert captured_plan["update"] is True
    assert captured_plan["overwrite"] is False
    assert captured_plan["new"] is False
    assert captured_plan["dry_run"] is False
    assert captured_plan["resume"] is True
    assert captured_plan["window_before"] == 3
    assert captured_plan["window_after"] == 4
    assert captured_plan["out"] == tmp_path
    assert captured_plan["chat_record"] == ChatRecord(
        id=100,
        title="Group",
        username="group",
        type="group",
    )
    assert captured_plan["target_record"] == SenderRecord(
        id=7,
        username="target",
        display_name="Target",
    )
    assert captured_options["download_media"] is False
    assert captured_options["resume"] is True
    assert captured_options["export_id"] == "abc12345"
    assert captured_upsert["export_id"] == "abc12345"


def test_export_command_overwrite_resets_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_reset: dict[str, object] = {}

    _install_export_command_fakes(
        monkeypatch,
        captured_plan={},
        captured_options={},
        captured_upsert={},
        should_reset=True,
        capture_reset=captured_reset,
    )

    result = runner.invoke(
        app,
        ["export", "--chat", "group", "--overwrite", "--out", str(tmp_path)],
    )

    assert result.exit_code == 0, result.output
    assert captured_reset["out_dir"] == tmp_path / "planned"


def test_export_command_rejects_multiple_existing_export_actions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cli,
        "_config",
        lambda env_file: SimpleNamespace(phone="+10000000000", timezone="Asia/Taipei"),
    )

    result = runner.invoke(
        app,
        ["export", "--chat", "group", "--update", "--new"],
    )

    assert result.exit_code != 0
    assert "Use only one of: --update, --overwrite, or --new." in result.output


def test_export_command_existing_export_error_includes_id_and_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_export_command_fakes(
        monkeypatch,
        captured_plan={},
        captured_options={},
        captured_upsert={},
    )
    entry = ExportEntry(
        id="abc12345",
        uuid="abc12345-0000-4000-8000-000000000000",
        root_dir=tmp_path / "existing",
        messages_path=tmp_path / "existing" / "messages.jsonl",
        updated_at="2026-01-01 00:00:00",
        chat="Group",
        target="Target",
        mode="group_slice",
        date_scope="2026-01-01",
        message_count=1,
        path_key="path-key",
        criteria_hash="criteria-hash",
    )

    def raise_existing(**kwargs: object) -> object:
        raise ExistingExportError(entry)

    monkeypatch.setattr(cli, "plan_export", raise_existing)

    result = runner.invoke(app, ["export", "--chat", "group", "--out", str(tmp_path)])

    assert result.exit_code == 1
    assert "id=abc12345" in result.output
    assert "existing" in result.output
    assert "--update to resume" in result.output


def test_exports_doctor_exits_nonzero_on_errors(tmp_path: Path) -> None:
    export_dir = tmp_path / "chat" / "2026-01-01"
    export_dir.mkdir(parents=True)
    (export_dir / "manifest.json").write_text("{}", encoding="utf-8")
    append_jsonl(export_dir / "messages.jsonl", {"id": 1})
    (tmp_path / ".index.json").write_text('{"version":1,"exports":[]}', encoding="utf-8")

    result = runner.invoke(app, ["exports", "doctor", "--root", str(tmp_path)])

    assert result.exit_code == 1
    assert "unindexed_export" in result.output


def test_render_html_supports_latest_export_selector(tmp_path: Path) -> None:
    root = tmp_path / "exports"
    export_dir = _write_renderable_export(root, export_id="abc12345")

    result = runner.invoke(
        app,
        ["render", "html", "--latest", "--exports-root", str(root)],
    )

    assert result.exit_code == 0, result.output
    assert (export_dir / "messages.html").exists()
    assert "messages.html" in result.output


def test_render_md_supports_stable_export_id(tmp_path: Path) -> None:
    root = tmp_path / "exports"
    export_dir = _write_renderable_export(root, export_id="abc12345")

    result = runner.invoke(
        app,
        ["render", "md", "--export", "abc12345", "--exports-root", str(root)],
    )

    assert result.exit_code == 0, result.output
    assert (export_dir / "messages.md").exists()
    assert "messages.md" in result.output


def test_render_rejects_multiple_input_selectors(tmp_path: Path) -> None:
    export_dir = _write_renderable_export(tmp_path / "exports", export_id="abc12345")

    result = runner.invoke(
        app,
        ["render", "html", str(export_dir / "messages.jsonl"), "--latest"],
    )

    assert result.exit_code != 0
    assert "Provide exactly one of: INPUT_PATH, --latest, or --export." in result.output


def _write_renderable_export(root: Path, *, export_id: str) -> Path:
    export_dir = root / "private__u7" / "2026-01-01"
    export_dir.mkdir(parents=True)
    manifest = {
        "id": export_id,
        "uuid": f"{export_id}-0000-4000-8000-000000000000",
        "updated_at": "2026-01-01T00:00:00Z",
        "chat": {"id": 7, "title": "Alice", "type": "private"},
        "target_sender": {"id": 7, "display_name": "Alice"},
        "mode": "private",
        "path_key": "path-key",
        "criteria_hash": "criteria-hash",
        "messages_path": "messages.jsonl",
        "stats": {"selected": 1},
        "runs": [{"ran_at": "2026-01-01T00:00:00Z"}],
    }
    (export_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    append_jsonl(
        export_dir / "messages.jsonl",
        {
            "id": 1,
            "date": "2026-01-01T00:00:00+00:00",
            "chat": {"id": 7},
            "sender": {"id": 7, "display_name": "Alice"},
            "text": "hello",
            "context_kind": "private",
            "media": [],
        },
    )
    return export_dir


def _install_export_command_fakes(
    monkeypatch: pytest.MonkeyPatch,
    *,
    captured_plan: dict[str, object],
    captured_options: dict[str, object],
    captured_upsert: dict[str, object],
    should_reset: bool = False,
    capture_reset: dict[str, object] | None = None,
) -> None:
    monkeypatch.setattr(
        cli,
        "_config",
        lambda env_file: SimpleNamespace(phone="+10000000000", timezone="Asia/Taipei"),
    )
    monkeypatch.setattr(cli, "TelethonGateway", _FakeTelethonGateway)

    def fake_plan_export(**kwargs: object) -> ExportPlan:
        captured_plan.update(kwargs)
        out = kwargs["out"]
        assert isinstance(out, Path)
        return ExportPlan(
            export_id="abc12345",
            export_uuid="abc12345-0000-4000-8000-000000000000",
            out_dir=out / "planned",
            resume=bool(kwargs["resume"]),
            should_reset=should_reset,
            mode="group_slice",
            source={"chat_ref": kwargs["chat_ref"]},
            path_key="path-key",
            criteria_hash="criteria-hash",
            chat_label="Group",
            target_label="Target",
            scope=str(kwargs["date_label"]),
        )

    async def fake_export_chat(
        gateway: object,
        options: ExportOptions,
        *,
        progress: object | None = None,
    ) -> ExportResult:
        captured_options.update(_export_options_payload(options))
        out_dir = captured_options["out_dir"]
        assert isinstance(out_dir, Path)
        return ExportResult(
            out_dir=out_dir,
            total_seen=10,
            selected=2,
            written=2,
            media_updated=0,
            skipped_existing=0,
            target_messages=2,
            dry_run=bool(captured_options["dry_run"]),
        )

    def fake_upsert_export_record(root: Path, **kwargs: object) -> object:
        captured_upsert["root"] = root
        captured_upsert.update(kwargs)
        return None

    def fake_reset_export_payload(out_dir: Path) -> None:
        if capture_reset is not None:
            capture_reset["out_dir"] = out_dir

    monkeypatch.setattr(cli, "plan_export", fake_plan_export)
    monkeypatch.setattr(cli, "export_chat", fake_export_chat)
    monkeypatch.setattr(cli, "upsert_export_record", fake_upsert_export_record)
    monkeypatch.setattr(cli, "reset_export_payload", fake_reset_export_payload)


def _export_options_payload(options: ExportOptions) -> dict[str, object]:
    return {
        "chat": options.chat,
        "sender": options.sender,
        "out_dir": options.out_dir,
        "download_media": options.download_media,
        "dry_run": options.dry_run,
        "resume": options.resume,
        "export_id": options.export_id,
        "export_uuid": options.export_uuid,
        "path_key": options.path_key,
        "criteria_hash": options.criteria_hash,
    }


class _FakeTelethonGateway:
    @classmethod
    def from_config(cls, cfg: object) -> "_FakeTelethonGateway":
        return cls()

    async def __aenter__(self) -> "_FakeTelethonGateway":
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None

    async def ensure_authorized(self, *, phone: str) -> None:
        return None

    async def resolve_chat(self, value: str) -> object:
        return SimpleNamespace(id=100, title="Group", username="group", private=False)

    async def resolve_user(self, value: str) -> object:
        return SimpleNamespace(id=7, title="Target", username="target")

    def chat_record(self, entity: object) -> ChatRecord:
        return ChatRecord(id=100, title="Group", username="group", type="group")

    def sender_record(self, entity: object) -> SenderRecord:
        return SenderRecord(id=7, username="target", display_name="Target")

    def is_private_chat(self, entity: object) -> bool:
        return False
