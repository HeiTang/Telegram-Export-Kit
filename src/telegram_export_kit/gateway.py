from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path

from telegram_export_kit.models import (
    ChatRecord,
    ContextKind,
    MediaRecord,
    MessageRecord,
    SenderRecord,
)


class TelegramGateway(ABC):
    @abstractmethod
    async def resolve_chat(self, value: str) -> object:
        raise NotImplementedError

    @abstractmethod
    async def resolve_user(self, value: str) -> object:
        raise NotImplementedError

    @abstractmethod
    def chat_record(self, entity: object) -> ChatRecord:
        raise NotImplementedError

    @abstractmethod
    def sender_record(self, entity: object) -> SenderRecord:
        raise NotImplementedError

    @abstractmethod
    def entity_id(self, entity: object) -> int:
        raise NotImplementedError

    @abstractmethod
    def message_sender_id(self, message: object) -> int | None:
        raise NotImplementedError

    @abstractmethod
    def message_sort_key(self, message: object) -> tuple[datetime, int]:
        raise NotImplementedError

    @abstractmethod
    def is_private_chat(self, entity: object) -> bool:
        raise NotImplementedError

    @abstractmethod
    def iter_messages(
        self,
        chat: object,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> AsyncIterator[object]:
        raise NotImplementedError

    @abstractmethod
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
        raise NotImplementedError

    @abstractmethod
    async def download_media(
        self,
        message: object,
        *,
        assets_dir: Path,
    ) -> list[MediaRecord]:
        raise NotImplementedError
