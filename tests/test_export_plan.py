from datetime import UTC, datetime
from pathlib import Path

import pytest

from telegram_export_kit.export_index import upsert_export_record
from telegram_export_kit.export_plan import (
    ExistingExportError,
    ExportPlan,
    PathCollisionError,
    default_export_dir,
    plan_export,
)
from telegram_export_kit.models import ChatRecord, SenderRecord


def test_default_export_dir_uses_stable_entity_ids() -> None:
    chat = ChatRecord(id=100, title="Raw / Title", username="group_name", type="group")
    target = SenderRecord(id=7, username="alice", display_name="Alice / Bob")

    assert default_export_dir(
        out=Path("exports"),
        chat_record=chat,
        target_record=target,
        date_label="2026-01-01",
        flat=False,
    ) == Path("exports/group__c100__u7/2026-01-01")


def test_default_export_dir_uses_private_chat_id_for_private_scope() -> None:
    chat = ChatRecord(id=7, title="Alice / Bob", username=None, type="private")
    target = SenderRecord(id=7, username=None, display_name="Alice / Bob")

    assert default_export_dir(
        out=Path("exports"),
        chat_record=chat,
        target_record=target,
        date_label="2026-01-01",
        flat=False,
    ) == Path("exports/private__u7/2026-01-01")


def test_plan_export_rejects_existing_export_without_action(tmp_path: Path) -> None:
    chat = ChatRecord(id=100, title="Group", username="group", type="group")
    target = SenderRecord(id=7, username="alice", display_name="Alice")
    first = plan_export(
        out=tmp_path,
        chat_ref="raw-group",
        sender_ref="raw-alice",
        chat_record=chat,
        target_record=target,
        date_label="2026-01-01",
        date="2026-01-01",
        start_date=None,
        end_date=None,
        since=datetime(2025, 12, 31, 16, tzinfo=UTC),
        until=datetime(2026, 1, 1, 16, tzinfo=UTC),
        timezone="Asia/Taipei",
        window_before=20,
        window_after=20,
        flat=False,
        update=False,
        overwrite=False,
        new=False,
        dry_run=False,
        resume=True,
    )
    first.out_dir.mkdir(parents=True)
    (first.out_dir / "messages.jsonl").write_text("{}\n")
    upsert_export_record(
        tmp_path,
        export_id=first.export_id,
        export_uuid=first.export_uuid,
        path=first.out_dir,
        path_key=first.path_key,
        criteria_hash=first.criteria_hash,
        chat=first.chat_label,
        target=first.target_label,
        mode=first.mode,
        scope=first.scope,
        message_count=1,
    )

    with pytest.raises(ExistingExportError):
        plan_export(
            out=tmp_path,
            chat_ref="100",
            sender_ref="7",
            chat_record=chat,
            target_record=target,
            date_label="2026-01-01",
            date="2026-01-01",
            start_date=None,
            end_date=None,
            since=datetime(2025, 12, 31, 16, tzinfo=UTC),
            until=datetime(2026, 1, 1, 16, tzinfo=UTC),
            timezone="Asia/Taipei",
            window_before=20,
            window_after=20,
            flat=False,
            update=False,
            overwrite=False,
            new=False,
            dry_run=False,
            resume=True,
        )


def test_plan_export_detects_same_path_key_different_criteria(tmp_path: Path) -> None:
    chat = ChatRecord(id=100, title="Group", username="group", type="group")
    target = SenderRecord(id=7, username="alice", display_name="Alice")
    first = plan_export(
        out=tmp_path,
        chat_ref="group",
        sender_ref="alice",
        chat_record=chat,
        target_record=target,
        date_label="2026-01-01",
        date="2026-01-01",
        start_date=None,
        end_date=None,
        since=datetime(2025, 12, 31, 16, tzinfo=UTC),
        until=datetime(2026, 1, 1, 16, tzinfo=UTC),
        timezone="Asia/Taipei",
        window_before=20,
        window_after=20,
        flat=False,
        update=False,
        overwrite=False,
        new=False,
        dry_run=False,
        resume=True,
    )
    first.out_dir.mkdir(parents=True)
    (first.out_dir / "messages.jsonl").write_text("{}\n")
    upsert_export_record(
        tmp_path,
        export_id=first.export_id,
        export_uuid=first.export_uuid,
        path=first.out_dir,
        path_key=first.path_key,
        criteria_hash=first.criteria_hash,
        chat=first.chat_label,
        target=first.target_label,
        mode=first.mode,
        scope=first.scope,
        message_count=1,
    )

    with pytest.raises(PathCollisionError):
        plan_export(
            out=tmp_path,
            chat_ref="group",
            sender_ref="alice",
            chat_record=chat,
            target_record=target,
            date_label="2026-01-01",
            date="2026-01-01",
            start_date=None,
            end_date=None,
            since=datetime(2025, 12, 31, 16, tzinfo=UTC),
            until=datetime(2026, 1, 1, 16, tzinfo=UTC),
            timezone="Asia/Taipei",
            window_before=10,
            window_after=10,
            flat=False,
            update=False,
            overwrite=False,
            new=False,
            dry_run=False,
            resume=True,
        )


def test_plan_export_dry_run_reuses_existing_criteria_without_action(tmp_path: Path) -> None:
    chat = ChatRecord(id=100, title="Group", username="group", type="group")
    target = SenderRecord(id=7, username="alice", display_name="Alice")
    first = _seed_indexed_plan(tmp_path, chat=chat, target=target, window_before=20)

    planned = plan_export(
        out=tmp_path,
        chat_ref="group",
        sender_ref="alice",
        chat_record=chat,
        target_record=target,
        date_label="2026-01-01",
        date="2026-01-01",
        start_date=None,
        end_date=None,
        since=datetime(2025, 12, 31, 16, tzinfo=UTC),
        until=datetime(2026, 1, 1, 16, tzinfo=UTC),
        timezone="Asia/Taipei",
        window_before=20,
        window_after=20,
        flat=False,
        update=False,
        overwrite=False,
        new=False,
        dry_run=True,
        resume=True,
    )

    assert planned.export_id == first.export_id
    assert planned.out_dir == first.out_dir
    assert planned.resume is True
    assert planned.should_reset is False


def test_plan_export_dry_run_allows_path_collision_without_writing(tmp_path: Path) -> None:
    chat = ChatRecord(id=100, title="Group", username="group", type="group")
    target = SenderRecord(id=7, username="alice", display_name="Alice")
    first = _seed_indexed_plan(tmp_path, chat=chat, target=target, window_before=20)

    planned = plan_export(
        out=tmp_path,
        chat_ref="group",
        sender_ref="alice",
        chat_record=chat,
        target_record=target,
        date_label="2026-01-01",
        date="2026-01-01",
        start_date=None,
        end_date=None,
        since=datetime(2025, 12, 31, 16, tzinfo=UTC),
        until=datetime(2026, 1, 1, 16, tzinfo=UTC),
        timezone="Asia/Taipei",
        window_before=10,
        window_after=10,
        flat=False,
        update=False,
        overwrite=False,
        new=False,
        dry_run=True,
        resume=True,
    )

    assert planned.path_key == first.path_key
    assert planned.criteria_hash != first.criteria_hash
    assert planned.out_dir == first.out_dir


def _seed_indexed_plan(
    root: Path,
    *,
    chat: ChatRecord,
    target: SenderRecord,
    window_before: int,
) -> ExportPlan:
    plan = plan_export(
        out=root,
        chat_ref="group",
        sender_ref="alice",
        chat_record=chat,
        target_record=target,
        date_label="2026-01-01",
        date="2026-01-01",
        start_date=None,
        end_date=None,
        since=datetime(2025, 12, 31, 16, tzinfo=UTC),
        until=datetime(2026, 1, 1, 16, tzinfo=UTC),
        timezone="Asia/Taipei",
        window_before=window_before,
        window_after=20,
        flat=False,
        update=False,
        overwrite=False,
        new=False,
        dry_run=False,
        resume=True,
    )
    plan.out_dir.mkdir(parents=True)
    (plan.out_dir / "messages.jsonl").write_text("{}\n")
    upsert_export_record(
        root,
        export_id=plan.export_id,
        export_uuid=plan.export_uuid,
        path=plan.out_dir,
        path_key=plan.path_key,
        criteria_hash=plan.criteria_hash,
        chat=plan.chat_label,
        target=plan.target_label,
        mode=plan.mode,
        scope=plan.scope,
        message_count=1,
    )
    return plan
