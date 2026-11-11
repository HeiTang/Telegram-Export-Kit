from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

INDEX_NAME = ".index.json"


@dataclass(frozen=True)
class ExportEntry:
    id: str
    uuid: str
    root_dir: Path
    messages_path: Path
    updated_at: str
    chat: str
    target: str
    mode: str
    date_scope: str
    message_count: int
    path_key: str
    criteria_hash: str


@dataclass(frozen=True)
class ExportIndexIssue:
    severity: Literal["error", "warning"]
    code: str
    message: str
    path: Path | None = None


@dataclass(frozen=True)
class ExportIndexDoctorResult:
    issues: list[ExportIndexIssue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(issue.severity == "error" for issue in self.issues)

    @property
    def error_count(self) -> int:
        return sum(1 for issue in self.issues if issue.severity == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for issue in self.issues if issue.severity == "warning")


def canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def hash_payload(payload: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def build_path_key(*, chat_id: int, target_id: int | None, date_scope: str) -> str:
    return hash_payload(
        {
            "chat_id": chat_id,
            "target_id": target_id,
            "date_scope": date_scope,
        }
    )


def build_criteria_hash(
    *,
    chat_id: int,
    target_id: int | None,
    mode: Literal["private", "group_slice", "full_chat"],
    since: datetime | None,
    until: datetime | None,
    window_before: int,
    window_after: int,
) -> str:
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "target_id": target_id,
        "mode": mode,
        "since": _datetime_value(since),
        "until": _datetime_value(until),
    }
    if mode == "group_slice":
        payload["window_before"] = window_before
        payload["window_after"] = window_after
    return hash_payload(payload)


def generate_export_identity(existing_ids: set[str] | None = None) -> tuple[str, str]:
    existing_ids = existing_ids or set()
    while True:
        value = str(uuid.uuid4())
        short_id = value.replace("-", "")[:8]
        if short_id not in existing_ids:
            return short_id, value


def discover_exports(root: Path = Path("exports")) -> list[ExportEntry]:
    records = _ensure_index(root)
    entries = [_entry_from_record(root, record) for record in records]
    entries = [entry for entry in entries if entry.messages_path.exists()]
    entries.sort(
        key=lambda entry: (_sort_time_from_label(entry.updated_at), str(entry.root_dir)),
        reverse=True,
    )
    return entries


def rebuild_export_index(root: Path = Path("exports")) -> list[ExportEntry]:
    records = _bootstrap_records(root)
    _write_index(root, records)
    return discover_exports(root)


def doctor_export_index(root: Path = Path("exports")) -> ExportIndexDoctorResult:
    records = _ensure_index(root)
    issues: list[ExportIndexIssue] = []
    seen_ids: set[str] = set()
    seen_uuids: set[str] = set()
    indexed_dirs: set[Path] = set()

    for record in records:
        entry = _entry_from_record(root, record)
        indexed_dirs.add(entry.root_dir)
        if not entry.root_dir.exists():
            issues.append(
                ExportIndexIssue(
                    severity="error",
                    code="missing_export_dir",
                    message=f"export directory not found: {entry.root_dir}",
                    path=entry.root_dir,
                )
            )
            continue
        if not entry.messages_path.exists():
            issues.append(
                ExportIndexIssue(
                    severity="error",
                    code="missing_messages",
                    message=f"messages.jsonl not found: {entry.messages_path}",
                    path=entry.messages_path,
                )
            )
        manifest = _read_manifest(entry.root_dir)
        if not manifest:
            issues.append(
                ExportIndexIssue(
                    severity="error",
                    code="missing_manifest",
                    message=f"manifest.json not found or invalid: {entry.root_dir}",
                    path=entry.root_dir,
                )
            )
        if entry.id and entry.id in seen_ids:
            issues.append(
                ExportIndexIssue(
                    severity="error",
                    code="duplicate_id",
                    message=f"duplicate export id: {entry.id}",
                    path=entry.root_dir,
                )
            )
        if entry.id:
            seen_ids.add(entry.id)

        if entry.uuid and entry.uuid in seen_uuids:
            issues.append(
                ExportIndexIssue(
                    severity="error",
                    code="duplicate_uuid",
                    message=f"duplicate export uuid: {entry.uuid}",
                    path=entry.root_dir,
                )
            )
        if entry.uuid:
            seen_uuids.add(entry.uuid)

        if manifest:
            _append_manifest_identity_issues(manifest, entry.root_dir, issues)
            _append_index_manifest_mismatches(record, manifest, entry.root_dir, issues)

    for messages_path in sorted(root.glob("**/messages.jsonl")):
        if any(
            part.startswith(".overwrite-") for part in messages_path.relative_to(root).parts[:-1]
        ):
            continue
        export_dir = messages_path.parent
        if export_dir not in indexed_dirs:
            issues.append(
                ExportIndexIssue(
                    severity="error",
                    code="unindexed_export",
                    message=f"export is not registered in {root / INDEX_NAME}",
                    path=export_dir,
                )
            )

    return ExportIndexDoctorResult(issues=issues)


def find_export_by_criteria(root: Path, criteria_hash: str) -> ExportEntry | None:
    for entry in discover_exports(root):
        if entry.criteria_hash == criteria_hash:
            return entry
    return None


def find_exports_by_path_key(root: Path, path_key: str) -> list[ExportEntry]:
    return [entry for entry in discover_exports(root) if entry.path_key == path_key]


def resolve_export_messages_path(
    path: Path | None,
    *,
    root: Path = Path("exports"),
    latest: bool = False,
    export_id: str | None = None,
) -> Path:
    selected_modes = sum([path is not None, latest, export_id is not None])
    if selected_modes != 1:
        raise ValueError("Provide exactly one of: path, --latest, or --export.")

    if path is not None:
        return path / "messages.jsonl" if path.is_dir() else path

    exports = discover_exports(root)
    if not exports:
        raise ValueError(f"No exports found under {root}.")

    if latest:
        return exports[0].messages_path

    assert export_id is not None
    for item in exports:
        if item.id == export_id:
            return item.messages_path
    raise ValueError(f"Export {export_id} not found. Run `tg-export exports list`.")


def upsert_export_record(
    root: Path,
    *,
    export_id: str,
    export_uuid: str,
    path: Path,
    path_key: str,
    criteria_hash: str,
    chat: str,
    target: str,
    mode: str,
    scope: str,
    message_count: int,
) -> ExportEntry:
    records = _ensure_index(root)
    now = datetime.now(UTC).isoformat()
    relative_path = _relative_posix(path, root)
    previous = next((record for record in records if record.get("id") == export_id), None)
    created_at = _string_value(previous.get("created_at")) if previous else now
    record = {
        "id": export_id,
        "uuid": export_uuid,
        "path": relative_path,
        "path_key": path_key,
        "criteria_hash": criteria_hash,
        "chat": chat,
        "target": target,
        "mode": mode,
        "scope": scope,
        "message_count": message_count,
        "created_at": created_at,
        "updated_at": now,
    }
    next_records = [item for item in records if item.get("id") != export_id]
    next_records.append(record)
    _write_index(root, next_records)
    return _entry_from_record(root, record)


def existing_export_ids(root: Path) -> set[str]:
    return {
        export_id
        for record in _ensure_index(root)
        if (export_id := _string_value(record.get("id"))) is not None
    }


def _ensure_index(root: Path) -> list[dict[str, Any]]:
    index_path = root / INDEX_NAME
    if index_path.exists():
        return _read_index(index_path)
    records = _bootstrap_records(root)
    if records:
        _write_index(root, records)
    return records


def _read_index(index_path: Path) -> list[dict[str, Any]]:
    try:
        payload = json.loads(index_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, dict):
        return []
    records = payload.get("exports")
    if not isinstance(records, list):
        return []
    return [record for record in records if isinstance(record, dict)]


def _write_index(root: Path, records: list[dict[str, Any]]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "exports": sorted(
            records,
            key=lambda record: _string_value(record.get("updated_at")) or "",
            reverse=True,
        ),
    }
    path = root / INDEX_NAME
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tmp_path.replace(path)


def _bootstrap_records(root: Path) -> list[dict[str, Any]]:
    if not root.exists():
        return []
    records: list[dict[str, Any]] = []
    for messages_path in sorted(root.glob("**/messages.jsonl")):
        if any(
            part.startswith(".overwrite-") for part in messages_path.relative_to(root).parts[:-1]
        ):
            continue
        root_dir = messages_path.parent
        manifest = _read_manifest(root_dir)
        sort_time = _sort_time(root_dir, manifest).isoformat()
        records.append(
            {
                "id": _string_value(manifest.get("id")) or "",
                "uuid": _string_value(manifest.get("uuid")) or "",
                "path": _relative_posix(root_dir, root),
                "path_key": _string_value(manifest.get("path_key")) or "",
                "criteria_hash": _string_value(manifest.get("criteria_hash")) or "",
                "chat": _chat_label(manifest) or root_dir.parent.name,
                "target": _target_label(manifest) or _target_from_slug(root_dir.parent.name),
                "mode": _string_value(manifest.get("mode")) or "",
                "scope": root_dir.name,
                "message_count": _message_count(messages_path, manifest),
                "created_at": _string_value(manifest.get("created_at")) or sort_time,
                "updated_at": _string_value(manifest.get("updated_at")) or sort_time,
            }
        )
    return records


def _entry_from_record(root: Path, record: dict[str, Any]) -> ExportEntry:
    root_dir = root / (_string_value(record.get("path")) or "")
    messages_path = root_dir / "messages.jsonl"
    manifest = _read_manifest(root_dir)
    updated_at = _parse_datetime(_string_value(record.get("updated_at")))
    target = (
        _string_value(record.get("target"))
        or _target_label(manifest)
        or _target_from_slug(root_dir.parent.name)
    )
    message_count = _int_value(record.get("message_count")) or _message_count(
        messages_path,
        manifest,
    )
    return ExportEntry(
        id=_string_value(manifest.get("id")) or _string_value(record.get("id")) or "",
        uuid=_string_value(manifest.get("uuid")) or _string_value(record.get("uuid")) or "",
        root_dir=root_dir,
        messages_path=messages_path,
        updated_at=_format_time(updated_at or _sort_time(root_dir, manifest)),
        chat=_string_value(record.get("chat")) or _chat_label(manifest) or root_dir.parent.name,
        target=target,
        mode=_string_value(record.get("mode")) or _string_value(manifest.get("mode")) or "",
        date_scope=_string_value(record.get("scope")) or root_dir.name,
        message_count=message_count,
        path_key=(
            _string_value(manifest.get("path_key"))
            or _string_value(record.get("path_key"))
            or ""
        ),
        criteria_hash=(
            _string_value(manifest.get("criteria_hash"))
            or _string_value(record.get("criteria_hash"))
            or ""
        ),
    )


def _read_manifest(root_dir: Path) -> dict[str, Any]:
    manifest_path = root_dir / "manifest.json"
    if not manifest_path.exists():
        return {}
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _append_manifest_identity_issues(
    manifest: dict[str, Any],
    root_dir: Path,
    issues: list[ExportIndexIssue],
) -> None:
    for field_name in ["id", "uuid", "path_key", "criteria_hash"]:
        if not _non_empty_string(manifest.get(field_name)):
            issues.append(
                ExportIndexIssue(
                    severity="error",
                    code="manifest_missing_identity",
                    message=f"manifest is missing non-empty {field_name}",
                    path=root_dir,
                )
            )


def _append_index_manifest_mismatches(
    record: dict[str, Any],
    manifest: dict[str, Any],
    root_dir: Path,
    issues: list[ExportIndexIssue],
) -> None:
    for field_name in ["id", "uuid", "path_key", "criteria_hash"]:
        index_value = _string_value(record.get(field_name))
        manifest_value = _string_value(manifest.get(field_name))
        if not _non_empty_string(manifest_value):
            continue
        if index_value != manifest_value:
            issues.append(
                ExportIndexIssue(
                    severity="error",
                    code="index_manifest_mismatch",
                    message=(
                        f"index {field_name} {index_value!r} "
                        f"differs from manifest {field_name} {manifest_value!r}"
                    ),
                    path=root_dir,
                )
            )


def _sort_time(root_dir: Path, manifest: dict[str, Any]) -> datetime:
    for key in ["updated_at", "created_at"]:
        parsed = _parse_datetime(_string_value(manifest.get(key)))
        if parsed is not None:
            return parsed
    return datetime.fromtimestamp(root_dir.stat().st_mtime, tz=UTC)


def _sort_time_from_label(value: str) -> datetime:
    return _parse_datetime(value) or datetime.min.replace(tzinfo=UTC)


def _parse_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _datetime_value(value: datetime | None) -> str | None:
    if value is None:
        return None
    parsed = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _format_time(value: datetime) -> str:
    return value.astimezone().strftime("%Y-%m-%d %H:%M:%S")


def _chat_label(manifest: dict[str, Any]) -> str | None:
    chat = manifest.get("chat")
    if not isinstance(chat, dict):
        return None
    return _first_string(chat, ["title", "username", "id"])


def _target_label(manifest: dict[str, Any]) -> str | None:
    target = manifest.get("target_sender")
    if target is None:
        return "all-senders"
    if not isinstance(target, dict):
        return None
    return _first_string(target, ["display_name", "username", "id"])


def _first_string(payload: dict[str, Any], keys: list[str]) -> str | None:
    for key in keys:
        value = payload.get(key)
        if value is not None:
            return str(value)
    return None


def _int_value(value: object) -> int | None:
    return value if isinstance(value, int) else None


def _string_value(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _non_empty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _target_from_slug(value: str) -> str:
    parts = value.rsplit("__", 1)
    return parts[1] if len(parts) == 2 else ""


def _message_count(path: Path, manifest: dict[str, Any]) -> int:
    stats = manifest.get("stats")
    if isinstance(stats, dict):
        selected = stats.get("selected")
        if isinstance(selected, int):
            return selected
    if not path.exists():
        return 0
    with path.open("rb") as fh:
        return sum(1 for line in fh if line.strip())


def _relative_posix(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()
