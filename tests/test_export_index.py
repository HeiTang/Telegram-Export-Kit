import hashlib
import json
from pathlib import Path

from telegram_export_kit.export_index import (
    discover_exports,
    doctor_export_index,
    rebuild_export_index,
    resolve_export_messages_path,
)
from telegram_export_kit.jsonl import append_jsonl


def _identity(name: str) -> tuple[str, str, str, str]:
    digest = hashlib.sha256(name.encode("utf-8")).hexdigest()
    export_id = digest[:8]
    return (
        export_id,
        f"{export_id}-0000-4000-8000-000000000000",
        f"path-{digest[:16]}",
        f"criteria-{digest[16:32]}",
    )


def _write_export(
    root: Path,
    name: str,
    *,
    updated_at: str,
    title: str,
    selected: int,
    include_identity: bool = True,
) -> Path:
    export_dir = root / name
    export_dir.mkdir(parents=True)
    manifest = {
        "updated_at": updated_at,
        "chat": {"title": title},
        "target_sender": None,
        "mode": "private",
        "stats": {"selected": selected},
    }
    if include_identity:
        export_id, export_uuid, path_key, criteria_hash = _identity(name)
        manifest.update(
            {
                "id": export_id,
                "uuid": export_uuid,
                "path_key": path_key,
                "criteria_hash": criteria_hash,
            }
        )
    (export_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    append_jsonl(export_dir / "messages.jsonl", {"id": 1})
    return export_dir


def test_discover_exports_sorts_newest_first(tmp_path: Path) -> None:
    old = _write_export(
        tmp_path,
        "chat__all/2026-01-01",
        updated_at="2026-01-01T00:00:00Z",
        title="Old Chat",
        selected=10,
    )
    new = _write_export(
        tmp_path,
        "chat__all/2026-01-02",
        updated_at="2026-01-02T00:00:00Z",
        title="New Chat",
        selected=20,
    )

    entries = discover_exports(tmp_path)

    assert [entry.root_dir for entry in entries] == [new, old]
    assert len({entry.id for entry in entries}) == 2
    assert all(len(entry.id) == 8 for entry in entries)
    assert entries[0].chat == "New Chat"
    assert entries[0].message_count == 20
    assert (tmp_path / ".index.json").exists()


def test_discover_exports_prefers_manifest_identity_over_stale_index(tmp_path: Path) -> None:
    export_dir = _write_export(
        tmp_path,
        "chat__all/2026-01-01",
        updated_at="2026-01-01T00:00:00Z",
        title="Old Chat",
        selected=10,
    )

    first = discover_exports(tmp_path)[0]
    payload = json.loads((tmp_path / ".index.json").read_text(encoding="utf-8"))
    payload["exports"][0]["id"] = "abc12345"
    (tmp_path / ".index.json").write_text(json.dumps(payload), encoding="utf-8")

    second = discover_exports(tmp_path)[0]

    assert first.root_dir == export_dir
    assert second.id == first.id


def test_rebuild_index_does_not_backfill_manifest_identity(tmp_path: Path) -> None:
    export_dir = _write_export(
        tmp_path,
        "chat__all/2026-01-01",
        updated_at="2026-01-01T00:00:00Z",
        title="Old Chat",
        selected=10,
        include_identity=False,
    )

    entries = rebuild_export_index(tmp_path)
    manifest = json.loads((export_dir / "manifest.json").read_text(encoding="utf-8"))
    result = doctor_export_index(tmp_path)

    assert len(entries) == 1
    assert "id" not in manifest
    assert "uuid" not in manifest
    assert "path_key" not in manifest
    assert "criteria_hash" not in manifest
    assert not result.ok
    assert [issue.code for issue in result.issues].count("manifest_missing_identity") == 4


def test_doctor_reports_duplicate_manifest_ids(tmp_path: Path) -> None:
    first = _write_export(
        tmp_path,
        "chat__all/2026-01-01",
        updated_at="2026-01-01T00:00:00Z",
        title="Old Chat",
        selected=10,
    )
    second = _write_export(
        tmp_path,
        "chat__all/2026-01-02",
        updated_at="2026-01-02T00:00:00Z",
        title="New Chat",
        selected=20,
    )
    for path in [first / "manifest.json", second / "manifest.json"]:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["id"] = "abc12345"
        manifest["uuid"] = "uuid"
        path.write_text(json.dumps(manifest), encoding="utf-8")

    result = doctor_export_index(tmp_path)

    assert not result.ok
    assert "duplicate_id" in {issue.code for issue in result.issues}


def test_doctor_reports_duplicate_manifest_uuids(tmp_path: Path) -> None:
    first = _write_export(
        tmp_path,
        "chat__all/2026-01-01",
        updated_at="2026-01-01T00:00:00Z",
        title="Old Chat",
        selected=10,
    )
    second = _write_export(
        tmp_path,
        "chat__all/2026-01-02",
        updated_at="2026-01-02T00:00:00Z",
        title="New Chat",
        selected=20,
    )
    for export_id, path in [
        ("abc12345", first / "manifest.json"),
        ("def67890", second / "manifest.json"),
    ]:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["id"] = export_id
        manifest["uuid"] = "same-uuid"
        path.write_text(json.dumps(manifest), encoding="utf-8")

    result = doctor_export_index(tmp_path)

    assert not result.ok
    assert "duplicate_uuid" in {issue.code for issue in result.issues}


def test_doctor_reports_stale_index_manifest_identity(tmp_path: Path) -> None:
    _write_export(
        tmp_path,
        "chat__all/2026-01-01",
        updated_at="2026-01-01T00:00:00Z",
        title="Old Chat",
        selected=10,
    )
    discover_exports(tmp_path)
    payload = json.loads((tmp_path / ".index.json").read_text(encoding="utf-8"))
    payload["exports"][0]["id"] = "stale-id"
    payload["exports"][0]["uuid"] = "stale-uuid"
    payload["exports"][0]["path_key"] = "stale-path-key"
    payload["exports"][0]["criteria_hash"] = "stale-criteria-hash"
    (tmp_path / ".index.json").write_text(json.dumps(payload), encoding="utf-8")

    result = doctor_export_index(tmp_path)

    assert not result.ok
    assert [issue.code for issue in result.issues].count("index_manifest_mismatch") == 4


def test_doctor_reports_missing_messages_for_indexed_export(tmp_path: Path) -> None:
    export_dir = _write_export(
        tmp_path,
        "chat__all/2026-01-01",
        updated_at="2026-01-01T00:00:00Z",
        title="Old Chat",
        selected=10,
    )
    discover_exports(tmp_path)
    (export_dir / "messages.jsonl").unlink()

    result = doctor_export_index(tmp_path)

    assert not result.ok
    assert "missing_messages" in {issue.code for issue in result.issues}


def test_doctor_reports_unindexed_exports(tmp_path: Path) -> None:
    _write_export(
        tmp_path,
        "chat__all/2026-01-01",
        updated_at="2026-01-01T00:00:00Z",
        title="Old Chat",
        selected=10,
    )
    (tmp_path / ".index.json").write_text('{"version":1,"exports":[]}', encoding="utf-8")

    result = doctor_export_index(tmp_path)

    assert not result.ok
    assert "unindexed_export" in {issue.code for issue in result.issues}


def test_doctor_allows_separate_exports_with_same_path_key(tmp_path: Path) -> None:
    first = _write_export(
        tmp_path,
        "chat__all/2026-01-01",
        updated_at="2026-01-01T00:00:00Z",
        title="Old Chat",
        selected=10,
    )
    second = _write_export(
        tmp_path,
        "chat__all/2026-01-02",
        updated_at="2026-01-02T00:00:00Z",
        title="New Chat",
        selected=20,
    )
    for export_id, criteria_hash, path in [
        ("abc12345", "criteria-a", first / "manifest.json"),
        ("def67890", "criteria-b", second / "manifest.json"),
    ]:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["id"] = export_id
        manifest["uuid"] = f"{export_id}-uuid"
        manifest["path_key"] = "same-path-key"
        manifest["criteria_hash"] = criteria_hash
        path.write_text(json.dumps(manifest), encoding="utf-8")

    result = doctor_export_index(tmp_path)

    assert result.ok
    assert result.issues == []


def test_resolve_export_messages_path_supports_latest_and_stable_export_id(
    tmp_path: Path,
) -> None:
    old = _write_export(
        tmp_path,
        "chat__all/2026-01-01",
        updated_at="2026-01-01T00:00:00Z",
        title="Old Chat",
        selected=10,
    )
    new = _write_export(
        tmp_path,
        "chat__all/2026-01-02",
        updated_at="2026-01-02T00:00:00Z",
        title="New Chat",
        selected=20,
    )

    assert resolve_export_messages_path(None, root=tmp_path, latest=True) == new / "messages.jsonl"
    old_id = next(entry.id for entry in discover_exports(tmp_path) if entry.root_dir == old)

    assert (
        resolve_export_messages_path(None, root=tmp_path, export_id=old_id)
        == old / "messages.jsonl"
    )
