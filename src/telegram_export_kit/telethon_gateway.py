from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, cast

from telethon import TelegramClient, errors
from telethon.tl.types import Channel, Chat, User

from telegram_export_kit.config import AppConfig
from telegram_export_kit.gateway import TelegramGateway
from telegram_export_kit.models import (
    ChatRecord,
    ContextKind,
    MediaKind,
    MediaRecord,
    MessageRecord,
    SenderRecord,
)
from telegram_export_kit.utils import ensure_aware_utc, safe_filename, unique_path


class TelethonGateway(TelegramGateway):
    def __init__(self, client: TelegramClient) -> None:
        self.client = client

    @classmethod
    def from_config(cls, config: AppConfig) -> TelethonGateway:
        client = TelegramClient(config.session_arg, config.api_id, config.api_hash)
        return cls(client)

    async def __aenter__(self) -> TelethonGateway:
        await self.client.connect()
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        await self.client.disconnect()

    async def login(self, *, phone: str | None = None) -> None:
        await self.client.start(phone=phone)

    async def ensure_authorized(self, *, phone: str | None = None) -> None:
        if not await self.client.is_user_authorized():
            await self.client.start(phone=phone)

    async def resolve_chat(self, value: str) -> object:
        return await self.client.get_entity(_coerce_ref(value))

    async def resolve_user(self, value: str) -> object:
        return await self.client.get_entity(_coerce_ref(value))

    def chat_record(self, entity: object) -> ChatRecord:
        entity_id = self.entity_id(entity)
        username = getattr(entity, "username", None)

        if isinstance(entity, User):
            title = _display_name(entity)
            chat_type: Literal["private", "group", "channel", "unknown"] = "private"
        elif isinstance(entity, Chat):
            title = getattr(entity, "title", None)
            chat_type = "group"
        elif isinstance(entity, Channel):
            title = getattr(entity, "title", None)
            chat_type = "channel" if getattr(entity, "broadcast", False) else "group"
        else:
            title = getattr(entity, "title", None) or getattr(entity, "first_name", None)
            chat_type = "unknown"

        return ChatRecord(id=entity_id, title=title, username=username, type=chat_type)

    def sender_record(self, entity: object) -> SenderRecord:
        return SenderRecord(
            id=getattr(entity, "id", None),
            username=getattr(entity, "username", None),
            first_name=getattr(entity, "first_name", None),
            last_name=getattr(entity, "last_name", None),
            display_name=_display_name(entity),
            is_bot=getattr(entity, "bot", None),
            is_self=getattr(entity, "is_self", None),
        )

    def entity_id(self, entity: object) -> int:
        raw_id = getattr(entity, "id", None)
        if raw_id is None:
            raise ValueError(f"Entity has no id: {entity!r}")
        return int(raw_id)

    def message_sender_id(self, message: object) -> int | None:
        raw_sender_id = getattr(message, "sender_id", None)
        return int(raw_sender_id) if raw_sender_id is not None else None

    def message_sort_key(self, message: object) -> tuple[datetime, int]:
        msg = cast(Any, message)
        date = ensure_aware_utc(msg.date)
        return date, int(msg.id)

    def is_private_chat(self, entity: object) -> bool:
        return isinstance(entity, User)

    async def iter_messages(
        self,
        chat: object,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> AsyncIterator[object]:
        since_utc = ensure_aware_utc(since) if since else None
        until_utc = ensure_aware_utc(until) if until else None

        kwargs: dict[str, object] = {}
        if until_utc is not None:
            kwargs["offset_date"] = until_utc

        async for message in self.client.iter_messages(chat, **kwargs):
            if message.date is None:
                continue
            message_date = ensure_aware_utc(message.date)
            if until_utc and message_date >= until_utc:
                continue
            if since_utc and message_date < since_utc:
                break
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
        msg = cast(Any, message)
        sender = await msg.get_sender() if hasattr(msg, "get_sender") else None
        media = await self.download_media(message, assets_dir=assets_dir) if download_media else []

        if _is_sticker(message) and not media:
            media.append(MediaRecord(kind="document", skipped_reason="sticker"))

        return MessageRecord(
            chat=self.chat_record(chat),
            id=int(msg.id),
            date=ensure_aware_utc(msg.date),
            sender=self.sender_record(sender) if sender is not None else None,
            text=getattr(msg, "raw_text", None) or getattr(msg, "text", None),
            entities=_serialize_entities(getattr(msg, "entities", None)),
            reply_to_msg_id=getattr(msg, "reply_to_msg_id", None),
            forward=_serialize_forward(getattr(msg, "fwd_from", None)),
            grouped_id=getattr(msg, "grouped_id", None),
            edit_date=_optional_datetime(getattr(msg, "edit_date", None)),
            media=media,
            context_kind=context_kind,
            sender_match=(
                target_sender_id is not None and self.message_sender_id(message) == target_sender_id
            ),
            target_user_match=(
                target_sender_id is not None and self.message_sender_id(message) == target_sender_id
            ),
            source={"message_class": msg.__class__.__name__},
        )

    async def download_media(
        self,
        message: object,
        *,
        assets_dir: Path,
    ) -> list[MediaRecord]:
        msg = cast(Any, message)
        if not _has_downloadable_media(message):
            return []
        if _is_sticker(message):
            return [MediaRecord(kind="document", skipped_reason="sticker")]

        file_info = getattr(msg, "file", None)
        original_name = getattr(file_info, "name", None)
        ext = getattr(file_info, "ext", None) or ""
        base_name = original_name or f"message_{msg.id}{ext}"

        final_name = safe_filename(str(base_name), fallback=f"message_{msg.id}")
        destination = unique_path(assets_dir / final_name)
        destination.parent.mkdir(parents=True, exist_ok=True)

        try:
            downloaded = await msg.download_media(file=str(destination))
        except errors.FloodWaitError:
            raise

        if not downloaded:
            return []

        downloaded_path = Path(downloaded)
        return [
            MediaRecord(
                kind=_media_kind(message),
                path=str(downloaded_path.relative_to(assets_dir.parent)),
                file_name=downloaded_path.name,
                mime_type=getattr(file_info, "mime_type", None),
                size=getattr(file_info, "size", None),
            )
        ]


def _coerce_ref(value: str) -> str | int:
    stripped = value.strip()
    if stripped.lstrip("-").isdigit():
        return int(stripped)
    return stripped


def _display_name(entity: object) -> str | None:
    first = getattr(entity, "first_name", None)
    last = getattr(entity, "last_name", None)
    title = getattr(entity, "title", None)
    username = getattr(entity, "username", None)
    name = " ".join(part for part in [first, last] if part)
    return name or title or username


def _serialize_entities(entities: list[object] | None) -> list[dict[str, Any]]:
    if not entities:
        return []
    serialized: list[dict[str, Any]] = []
    for entity in entities:
        payload = entity.to_dict() if hasattr(entity, "to_dict") else dict(entity.__dict__)
        payload.pop("_", None)
        serialized.append(payload)
    return serialized


def _serialize_forward(value: object | None) -> dict[str, Any] | None:
    if value is None:
        return None
    payload = value.to_dict() if hasattr(value, "to_dict") else dict(getattr(value, "__dict__", {}))
    payload.pop("_", None)
    return payload


def _optional_datetime(value: datetime | None) -> datetime | None:
    return ensure_aware_utc(value) if value else None


def _is_sticker(message: object) -> bool:
    return bool(getattr(message, "sticker", False))


def _has_downloadable_media(message: object) -> bool:
    return bool(
        getattr(message, "media", None)
        or getattr(message, "photo", None)
        or getattr(message, "document", None)
    )


def _media_kind(message: object) -> MediaKind:
    file_info = getattr(message, "file", None)
    mime_type = (getattr(file_info, "mime_type", None) or "").lower()
    if getattr(message, "photo", None):
        return "photo"
    if "video" in mime_type:
        return "video"
    if "audio" in mime_type:
        return "audio"
    if getattr(message, "voice", False):
        return "voice"
    if getattr(message, "document", None):
        return "document"
    return "unknown"
