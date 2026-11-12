from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

Severity = Literal["error", "warning"]


@dataclass(frozen=True)
class VerifyIssue:
    severity: Severity
    code: str
    message: str
    line: int | None = None


@dataclass(frozen=True)
class VerifyResult:
    root_dir: Path
    messages_path: Path
    message_count: int
    asset_count: int
    missing_reply_count: int
    issues: list[VerifyIssue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(issue.severity == "error" for issue in self.issues)

    @property
    def error_count(self) -> int:
        return sum(1 for issue in self.issues if issue.severity == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for issue in self.issues if issue.severity == "warning")


def verify_export(path: Path) -> VerifyResult:
    messages_path = path if path.is_file() else path / "messages.jsonl"
    root_dir = messages_path.parent
    issues: list[VerifyIssue] = []
    if (root_dir / ".overwrite-backup").exists():
        issues.append(
            _error("unfinished_overwrite", "recover .overwrite-backup before using this export")
        )
    records = _read_records(messages_path, issues)
    seen_ids: set[int] = set()
    reply_ids: set[int] = set()
    asset_count = 0
    previous_key: tuple[datetime, int] | None = None

    for row in records:
        line = row.line
        record = row.record
        message_id = _message_id(record)
        if message_id is None:
            issues.append(_error("missing_id", "message is missing integer id", line=line))
        elif message_id in seen_ids:
            issues.append(_error("duplicate_id", f"duplicate message id: {message_id}", line=line))
        elif message_id is not None:
            seen_ids.add(message_id)

        for field_name in ["date", "chat", "context_kind"]:
            if field_name not in record:
                issues.append(
                    _error(
                        "missing_field",
                        f"message {message_id or '<unknown>'} is missing {field_name}",
                        line=line,
                    )
                )

        current_key = _sort_key(record)
        if current_key is not None:
            if previous_key is not None and current_key < previous_key:
                issues.append(
                    _warning(
                        "sort_order",
                        f"message {message_id or '<unknown>'} is out of date/id order",
                        line=line,
                    )
                )
            previous_key = current_key

        reply_id = record.get("reply_to_msg_id")
        if isinstance(reply_id, int):
            reply_ids.add(reply_id)

        asset_count += _verify_media(root_dir, record, issues, line=line)

    missing_reply_count = 0
    for reply_id in sorted(reply_ids):
        if reply_id not in seen_ids:
            missing_reply_count += 1
            issues.append(_warning("missing_reply", f"reply target not exported: {reply_id}"))

    _verify_manifest(root_dir, issues, records=records)

    return VerifyResult(
        root_dir=root_dir,
        messages_path=messages_path,
        message_count=len(records),
        asset_count=asset_count,
        missing_reply_count=missing_reply_count,
        issues=issues,
    )


@dataclass(frozen=True)
class _JsonlRow:
    line: int
    record: dict[str, Any]


def _read_records(path: Path, issues: list[VerifyIssue]) -> list[_JsonlRow]:
    if not path.exists():
        issues.append(_error("missing_messages", f"messages.jsonl not found: {path}"))
        return []

    rows: list[_JsonlRow] = []
    with path.open("r", encoding="utf-8") as fh:
        for line_number, line in enumerate(fh, start=1):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                issues.append(_error("invalid_json", exc.msg, line=line_number))
                continue
            if not isinstance(payload, dict):
                issues.append(
                    _error("invalid_record", "JSONL row must be an object", line=line_number)
                )
                continue
            rows.append(_JsonlRow(line=line_number, record=payload))
    return rows


def _message_id(record: dict[str, Any]) -> int | None:
    raw_id = record.get("id")
    return raw_id if isinstance(raw_id, int) else None


def _sort_key(record: dict[str, Any]) -> tuple[datetime, int] | None:
    raw_date = record.get("date")
    message_id = _message_id(record)
    if not isinstance(raw_date, str) or message_id is None:
        return None
    try:
        parsed = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed, message_id


def _verify_media(
    root_dir: Path,
    record: dict[str, Any],
    issues: list[VerifyIssue],
    *,
    line: int,
) -> int:
    media = record.get("media")
    if media is None:
        return 0
    if not isinstance(media, list):
        issues.append(_error("invalid_media", "media must be a list", line=line))
        return 0

    asset_count = 0
    message_id = _message_id(record)
    for item in media:
        if not isinstance(item, dict):
            issues.append(_error("invalid_media", "media item must be an object", line=line))
            continue
        path = item.get("path")
        if not isinstance(path, str) or not path:
            continue
        asset_count += 1
        if not (root_dir / path).exists():
            issues.append(
                _error(
                    "missing_asset",
                    f"message {message_id or '<unknown>'} references missing asset: {path}",
                    line=line,
                )
            )
    return asset_count


def _verify_manifest(
    root_dir: Path, issues: list[VerifyIssue], *, records: list[_JsonlRow]
) -> None:
    manifest_path = root_dir / "manifest.json"
    if not manifest_path.exists():
        issues.append(_warning("missing_manifest", f"manifest.json not found: {manifest_path}"))
        return
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        issues.append(_error("invalid_manifest", exc.msg))
        return
    if not isinstance(payload, dict):
        issues.append(_error("invalid_manifest", "manifest must be a JSON object"))
        return

    for field_name in ["id", "uuid", "path_key", "criteria_hash"]:
        if not _non_empty_string(payload.get(field_name)):
            issues.append(
                _error(
                    "manifest_missing_field",
                    f"manifest is missing non-empty {field_name}",
                )
            )

    runs = payload.get("runs")
    if not isinstance(runs, list) or not runs:
        issues.append(_error("manifest_invalid_runs", "manifest runs must be a non-empty list"))

    messages_path = payload.get("messages_path", "messages.jsonl")
    if messages_path != "messages.jsonl":
        issues.append(
            _error(
                "manifest_invalid_messages_path",
                "manifest messages_path must be messages.jsonl",
            )
        )

    mode = payload.get("mode")
    if mode not in {"private", "group_slice", "full_chat"}:
        issues.append(
            _error(
                "manifest_invalid_mode",
                "manifest mode must be private, group_slice, or full_chat",
            )
        )

    chat = payload.get("chat")
    if not isinstance(chat, dict) or not isinstance(chat.get("id"), int):
        issues.append(_error("manifest_invalid_chat", "manifest chat.id must be an integer"))
    else:
        for row in records:
            row_chat = row.record.get("chat")
            if not isinstance(row_chat, dict) or row_chat.get("id") != chat["id"]:
                issues.append(
                    _error("chat_mismatch", "message chat.id differs from manifest", line=row.line)
                )

    stats = payload.get("stats")
    if not isinstance(stats, dict):
        issues.append(_error("manifest_invalid_stats", "manifest stats must be an object"))
    else:
        selected = stats.get("selected")
        if not isinstance(selected, int):
            issues.append(
                _error("manifest_invalid_stats", "manifest stats.selected must be an integer")
            )
        elif selected != len(records):
            issues.append(
                _error(
                    "manifest_stats_mismatch",
                    f"manifest stats.selected {selected} differs from JSONL count {len(records)}",
                )
            )

    if isinstance(runs, list):
        for index, run in enumerate(runs, start=1):
            if not isinstance(run, dict):
                issues.append(
                    _error("manifest_invalid_run", f"manifest run #{index} must be an object")
                )
                continue
            ran_at = run.get("ran_at")
            if not isinstance(ran_at, str) or _parse_datetime(ran_at) is None:
                issues.append(
                    _error(
                        "manifest_invalid_run",
                        f"manifest run #{index} ran_at must be an ISO datetime",
                    )
                )


def _non_empty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _parse_datetime(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _error(code: str, message: str, *, line: int | None = None) -> VerifyIssue:
    return VerifyIssue(severity="error", code=code, message=message, line=line)


def _warning(code: str, message: str, *, line: int | None = None) -> VerifyIssue:
    return VerifyIssue(severity="warning", code=code, message=message, line=line)
