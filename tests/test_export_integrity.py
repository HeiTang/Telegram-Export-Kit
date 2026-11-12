from __future__ import annotations

import json
import shutil
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_exporter import FakeGateway, _messages
from typer.testing import CliRunner

from telegram_export_kit import cli
from telegram_export_kit.export_index import discover_exports, rebuild_export_index
from telegram_export_kit.export_plan import ExportPlanError, staged_overwrite
from telegram_export_kit.verify import verify_export

runner = CliRunner()


class ConnectedFakeGateway(FakeGateway):
    async def __aenter__(self) -> ConnectedFakeGateway:
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        pass

    async def ensure_authorized(self, *, phone: str) -> None:
        pass


@pytest.fixture
def gateway(monkeypatch: pytest.MonkeyPatch) -> ConnectedFakeGateway:
    fake = ConnectedFakeGateway(_messages())
    monkeypatch.setattr(
        cli, "_config", lambda _: SimpleNamespace(phone="+10000000000", timezone="UTC")
    )
    monkeypatch.setattr(
        "telegram_export_kit.telethon_gateway.TelethonGateway.from_config", lambda _: fake
    )
    return fake


def export(root: Path, *flags: str) -> None:
    result = runner.invoke(
        cli.app, ["export", "--chat", "group", "--no-media", "--out", str(root), *flags]
    )
    assert result.exit_code == 0, (result.output, result.exception)


def payload(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file() and path.name != ".index.json"
    }


@pytest.mark.parametrize("action", [[], ["--update"], ["--overwrite"]])
def test_flat_cannot_mix_chats(
    tmp_path: Path, gateway: ConnectedFakeGateway, action: list[str]
) -> None:
    export(tmp_path, "--flat")
    before = payload(tmp_path)
    gateway.chat.id = 200
    result = runner.invoke(
        cli.app,
        ["export", "--chat", "other", "--flat", "--out", str(tmp_path), *action],
    )
    assert result.exit_code == 1
    assert "different or unidentified export" in result.output
    assert payload(tmp_path) == before


@pytest.mark.parametrize("manifest", [None, "{broken"])
def test_unidentified_payload_is_not_resumed(
    tmp_path: Path, gateway: ConnectedFakeGateway, manifest: str | None
) -> None:
    export(tmp_path, "--flat")
    manifest_path = tmp_path / "manifest.json"
    if manifest is None:
        manifest_path.unlink()
    else:
        manifest_path.write_text(manifest)
    before = payload(tmp_path)
    result = runner.invoke(
        cli.app, ["export", "--chat", "group", "--flat", "--update", "--out", str(tmp_path)]
    )
    assert result.exit_code == 1
    assert payload(tmp_path) == before


def test_verify_rejects_mixed_chat_with_line_number(
    tmp_path: Path, gateway: ConnectedFakeGateway
) -> None:
    export(tmp_path, "--flat")
    path = tmp_path / "messages.jsonl"
    lines = path.read_text().splitlines()
    row = json.loads(lines[0])
    row["chat"]["id"] = 200
    lines[0] = json.dumps(row)
    path.write_text("\n".join(lines) + "\n")
    result = verify_export(tmp_path)
    assert not result.ok
    assert [(i.code, i.line) for i in result.issues] == [("chat_mismatch", 1)]
    assert runner.invoke(cli.app, ["verify", str(tmp_path)]).exit_code == 1


def test_update_preserves_archive_count_when_source_shrinks(
    tmp_path: Path, gateway: ConnectedFakeGateway
) -> None:
    export(tmp_path, "--flat")
    first = json.loads((tmp_path / "manifest.json").read_text())
    original_messages = (tmp_path / "messages.jsonl").read_bytes()
    gateway.messages = gateway.messages[:-1]
    export(tmp_path, "--flat", "--update")
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert manifest["id"] == first["id"]
    assert manifest["uuid"] == first["uuid"]
    assert manifest["stats"]["selected"] == 8
    assert manifest["runs"][-1]["stats"]["selected"] == 7
    assert (tmp_path / "messages.jsonl").read_bytes() == original_messages
    assert discover_exports(tmp_path)[0].message_count == 8
    assert verify_export(tmp_path).ok


@pytest.mark.parametrize("private", [False, True])
def test_empty_export_supports_offline_commands(
    tmp_path: Path, gateway: ConnectedFakeGateway, private: bool
) -> None:
    gateway.messages = []
    gateway.chat.private = private
    export(tmp_path, "--flat")
    assert (tmp_path / "messages.jsonl").read_bytes() == b""
    entry = discover_exports(tmp_path)[0]
    assert entry.message_count == 0
    for args in [["verify"], ["search"], ["render", "html"], ["render", "md"]]:
        result = runner.invoke(
            cli.app, [*args, "--export", entry.id, "--exports-root", str(tmp_path)]
        )
        assert result.exit_code == 0, (result.output, result.exception)
    export(tmp_path, "--flat", "--update")
    assert verify_export(tmp_path).ok


@pytest.mark.parametrize("failure", ["scan", "media"])
def test_overwrite_failure_preserves_original(
    tmp_path: Path, gateway: ConnectedFakeGateway, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    export(tmp_path, "--flat")
    (tmp_path / "assets" / "original.txt").write_text("keep attachment")
    before = payload(tmp_path)

    async def fail(*args: object, **kwargs: object) -> object:
        raise OSError("simulated download failure")

    if failure == "scan":
        async def fail_scan(*args: object, **kwargs: object) -> AsyncIterator[object]:
            raise OSError("simulated scan failure")
            yield

        monkeypatch.setattr(gateway, "iter_messages", fail_scan)
    else:
        monkeypatch.setattr(gateway, "download_media", fail)
    result = runner.invoke(
        cli.app, ["export", "--chat", "group", "--flat", "--overwrite", "--out", str(tmp_path)]
    )
    assert result.exit_code == 1
    assert payload(tmp_path) == before
    assert verify_export(tmp_path).ok
    assert not list(tmp_path.glob(".overwrite-*"))


@pytest.mark.parametrize("message_count", [0, 2])
def test_overwrite_replaces_payload_and_preserves_identity(
    tmp_path: Path, gateway: ConnectedFakeGateway, message_count: int
) -> None:
    export(tmp_path, "--flat")
    before = json.loads((tmp_path / "manifest.json").read_text())
    (tmp_path / "assets" / "old.txt").write_text("old")
    gateway.messages = gateway.messages[:message_count]
    export(tmp_path, "--flat", "--overwrite")
    after = json.loads((tmp_path / "manifest.json").read_text())
    assert (after["id"], after["uuid"], after["created_at"]) == (
        before["id"],
        before["uuid"],
        before["created_at"],
    )
    assert len(after["runs"]) == 2
    assert verify_export(tmp_path).message_count == message_count
    assert verify_export(tmp_path).ok
    assert not (tmp_path / "assets" / "old.txt").exists()
    assert discover_exports(tmp_path)[0].message_count == message_count
    assert not list(tmp_path.glob(".overwrite-*"))


@pytest.mark.parametrize("fail_at", ["backup", "install"])
def test_overwrite_switch_failure_rolls_back(
    tmp_path: Path, gateway: ConnectedFakeGateway, monkeypatch: pytest.MonkeyPatch, fail_at: str
) -> None:
    export(tmp_path, "--flat")
    before = payload(tmp_path)
    original_replace = Path.replace
    failed = False

    def replace(path: Path, target: Path) -> Path:
        nonlocal failed
        is_install = (
            path.parent.name.startswith(".overwrite-") and path.parent.name != ".overwrite-backup"
        )
        is_backup = target.parent.name == ".overwrite-backup"
        if (
            not failed
            and path.name == "assets"
            and ((fail_at == "install" and is_install) or (fail_at == "backup" and is_backup))
        ):
            failed = True
            raise OSError("simulated rename failure")
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", replace)
    result = runner.invoke(
        cli.app, ["export", "--chat", "group", "--flat", "--overwrite", "--out", str(tmp_path)]
    )
    assert result.exit_code == 1
    assert failed
    assert payload(tmp_path) == before
    assert verify_export(tmp_path).ok


def test_overwrite_rejects_unverified_replacement(
    tmp_path: Path, gateway: ConnectedFakeGateway
) -> None:
    export(tmp_path, "--flat")
    before = payload(tmp_path)
    with (
        pytest.raises(ExportPlanError, match="failed verification"),
        staged_overwrite(tmp_path) as staging,
    ):
        (staging / "messages.jsonl").write_text("{broken\n")
    assert payload(tmp_path) == before


def test_interrupted_overwrite_is_blocked_and_hidden_from_index(
    tmp_path: Path, gateway: ConnectedFakeGateway
) -> None:
    export(tmp_path, "--flat")
    backup = tmp_path / ".overwrite-backup"
    backup.mkdir()
    shutil.copy2(tmp_path / "messages.jsonl", backup / "messages.jsonl")
    shutil.copy2(tmp_path / "manifest.json", backup / "manifest.json")
    before = payload(tmp_path)
    result = runner.invoke(
        cli.app, ["export", "--chat", "group", "--flat", "--update", "--out", str(tmp_path)]
    )
    assert result.exit_code == 1
    assert "Unfinished overwrite" in result.output
    assert payload(tmp_path) == before
    assert "unfinished_overwrite" in [i.code for i in verify_export(tmp_path).issues]
    assert len(rebuild_export_index(tmp_path)) == 1


def test_flat_new_remains_discoverable_after_move_and_index_rebuild(
    tmp_path: Path, gateway: ConnectedFakeGateway
) -> None:
    root = tmp_path / "original"
    export(root, "--flat")
    export(root, "--flat", "--new")
    entries = discover_exports(root)
    assert len(entries) == 2
    ids = {entry.id for entry in entries}
    moved = tmp_path / "moved"
    root.rename(moved)
    (moved / ".index.json").unlink()
    assert {entry.id for entry in rebuild_export_index(moved)} == ids
    for export_id in ids:
        for args in [["verify"], ["search", "--query", "m3"], ["render", "html"], ["render", "md"]]:
            result = runner.invoke(
                cli.app, [*args, "--export", export_id, "--exports-root", str(moved)]
            )
            assert result.exit_code == 0, (result.output, result.exception)
    assert runner.invoke(cli.app, ["exports", "doctor", "--root", str(moved)]).exit_code == 0


@pytest.mark.parametrize("reference", ["chat", "sender"])
@pytest.mark.parametrize("action", ["--update", "--overwrite", "--new"])
def test_export_rejects_reference_changes_after_planning(
    tmp_path: Path,
    gateway: ConnectedFakeGateway,
    monkeypatch: pytest.MonkeyPatch,
    reference: str,
    action: str,
) -> None:
    flags = ["--flat"]
    if reference == "sender":
        flags += ["--sender", "target", "--window-before", "0", "--window-after", "0"]
    export(tmp_path, *flags)
    before = payload(tmp_path)
    calls = 0

    async def resolve(value: str) -> object:
        nonlocal calls
        calls += 1
        entity = gateway.chat if reference == "chat" else gateway.user
        if calls == 2:
            entity.id += 1
        return entity

    monkeypatch.setattr(gateway, "resolve_chat" if reference == "chat" else "resolve_user", resolve)
    result = runner.invoke(
        cli.app,
        ["export", "--chat", "group", action, "--no-media", "--out", str(tmp_path), *flags],
    )
    assert result.exit_code == 1
    assert "changed since planning" in result.output
    assert payload(tmp_path) == before
