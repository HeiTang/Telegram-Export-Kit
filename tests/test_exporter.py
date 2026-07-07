from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from telegram_export_kit.exporter import export_chat
from telegram_export_kit.gateway import TelegramGateway
from telegram_export_kit.jsonl import read_jsonl
from telegram_export_kit.models import (
    ChatRecord,
    ContextKind,
    ExportOptions,
    MediaRecord,
    MessageRecord,
    SenderRecord,
)


@dataclass
class FakeEntity:
    id: int
    title: str | None = None
    username: str | None = None
    private: bool = False


@dataclass
class FakeMessage:
    id: int
    sender_id: int
    date: datetime
    raw_text: str
    has_media: bool = False


class FakeGateway(TelegramGateway):
    def __init__(self, messages: list[FakeMessage], *, private: bool = False) -> None:
        self.messages = messages
        self.chat = FakeEntity(100, title="Group", username="group", private=private)
        self.user = FakeEntity(7, title="Target", username="target")

    async def resolve_chat(self, value: str) -> object:
        return self.chat

    async def resolve_user(self, value: str) -> object:
        return self.user

    def chat_record(self, entity: object) -> ChatRecord:
        item = entity
        assert isinstance(item, FakeEntity)
        return ChatRecord(
            id=item.id,
            title=item.title,
            username=item.username,
            type="private" if item.private else "group",
        )

    def sender_record(self, entity: object) -> SenderRecord:
        item = entity
        assert isinstance(item, FakeEntity)
        return SenderRecord(id=item.id, username=item.username, display_name=item.title)

    def entity_id(self, entity: object) -> int:
        item = entity
        assert isinstance(item, FakeEntity)
        return item.id

    def message_sender_id(self, message: object) -> int | None:
        item = message
        assert isinstance(item, FakeMessage)
        return item.sender_id

    def message_sort_key(self, message: object) -> tuple[datetime, int]:
        item = message
        assert isinstance(item, FakeMessage)
        return item.date, item.id

    def is_private_chat(self, entity: object) -> bool:
        item = entity
        assert isinstance(item, FakeEntity)
        return item.private

    async def iter_messages(
        self,
        chat: object,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> AsyncIterator[object]:
        for message in self.messages:
            if since and message.date < since:
                continue
            if until and message.date >= until:
                continue
            yield message

    async def build_message_record(
        self,
        message: object,
        *,
        chat: object,
        context_kind: ContextKind,
        target_sender_id: int | None,
        assets_dir: Path,
        download_media: bool,
    ) -> MessageRecord:
        item = message
        assert isinstance(item, FakeMessage)
        return MessageRecord(
            chat=self.chat_record(chat),
            id=item.id,
            date=item.date,
            sender=SenderRecord(id=item.sender_id),
            text=item.raw_text,
            media=await self.download_media(item, assets_dir=assets_dir) if download_media else [],
            context_kind=context_kind,
            sender_match=target_sender_id is not None and item.sender_id == target_sender_id,
            target_user_match=target_sender_id is not None and item.sender_id == target_sender_id,
        )

    async def download_media(self, message: object, *, assets_dir: Path) -> list[MediaRecord]:
        item = message
        assert isinstance(item, FakeMessage)
        if not item.has_media:
            return []
        return [
            MediaRecord(
                kind="photo",
                path=f"assets/message_{item.id}.jpg",
                file_name=f"message_{item.id}.jpg",
            )
        ]


def _messages() -> list[FakeMessage]:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    senders = [1, 1, 7, 2, 7, 3, 3, 3]
    return [
        FakeMessage(
            id=index + 1,
            sender_id=sender_id,
            date=start + timedelta(minutes=index),
            raw_text=f"m{index + 1}",
        )
        for index, sender_id in enumerate(senders)
    ]


async def test_group_export_writes_merged_context_slice(tmp_path: Path) -> None:
    gateway = FakeGateway(_messages())
    result = await export_chat(
        gateway,
        ExportOptions(
            chat="group",
            sender="target",
            out_dir=tmp_path,
            window_before=1,
            window_after=1,
        ),
    )

    rows = list(read_jsonl(tmp_path / "messages.jsonl"))

    assert result.total_seen == 8
    assert result.target_messages == 2
    assert result.selected == 5
    assert result.written == 5
    assert [row["id"] for row in rows] == [2, 3, 4, 5, 6]
    assert [row["context_kind"] for row in rows] == ["before", "target", "after", "target", "after"]
    assert (tmp_path / "manifest.json").exists()


async def test_private_export_includes_whole_dialog(tmp_path: Path) -> None:
    gateway = FakeGateway(_messages(), private=True)
    result = await export_chat(
        gateway,
        ExportOptions(
            chat="target",
            out_dir=tmp_path,
            window_before=0,
            window_after=0,
        ),
    )

    rows = list(read_jsonl(tmp_path / "messages.jsonl"))

    assert result.selected == 8
    assert {row["context_kind"] for row in rows} == {"private"}


async def test_resume_skips_existing_message_ids(tmp_path: Path) -> None:
    gateway = FakeGateway(_messages())
    options = ExportOptions(
        chat="group",
        sender="target",
        out_dir=tmp_path,
        window_before=0,
        window_after=0,
    )

    first = await export_chat(gateway, options)
    second = await export_chat(gateway, options)

    assert first.written == 2
    assert second.written == 0
    assert second.media_updated == 0
    assert second.skipped_existing == 2
    assert len(list(read_jsonl(tmp_path / "messages.jsonl"))) == 2


async def test_resume_can_update_existing_records_with_media(tmp_path: Path) -> None:
    messages = _messages()
    messages[2].has_media = True
    gateway = FakeGateway(messages)
    options = ExportOptions(
        chat="group",
        sender="target",
        out_dir=tmp_path,
        window_before=0,
        window_after=0,
        download_media=False,
    )

    first = await export_chat(gateway, options)
    second = await export_chat(gateway, options.model_copy(update={"download_media": True}))
    rows = list(read_jsonl(tmp_path / "messages.jsonl"))

    assert first.written == 2
    assert second.written == 0
    assert second.media_updated == 1
    assert len(rows) == 2
    assert rows[0]["media"] == [
        {"kind": "photo", "path": "assets/message_3.jpg", "file_name": "message_3.jpg"}
    ]
    assert rows[1]["media"] == []


async def test_group_export_without_sender_exports_full_chat(tmp_path: Path) -> None:
    gateway = FakeGateway(_messages())
    result = await export_chat(gateway, ExportOptions(chat="group", out_dir=tmp_path))

    rows = list(read_jsonl(tmp_path / "messages.jsonl"))

    assert result.selected == 8
    assert result.target_messages == 0
    assert [row["id"] for row in rows] == list(range(1, 9))
    assert {row["context_kind"] for row in rows} == {"target"}
