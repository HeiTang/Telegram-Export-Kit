from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from telegram_export_kit.models import MediaRecord
from telegram_export_kit.telethon_gateway import TelethonGateway


@dataclass
class FakeHistoryMessage:
    id: int
    date: datetime


class FakeHistoryClient:
    def __init__(self, messages: list[FakeHistoryMessage]) -> None:
        self.messages = messages
        self.kwargs: dict[str, object] | None = None
        self.yielded = 0

    async def iter_messages(
        self,
        chat: object,
        **kwargs: object,
    ) -> AsyncIterator[FakeHistoryMessage]:
        self.kwargs = kwargs
        for message in self.messages:
            self.yielded += 1
            yield message


class StickerMessage:
    id = 123
    sticker = True
    media = True


async def test_stickers_are_not_downloaded(tmp_path: Path) -> None:
    gateway = TelethonGateway(client=cast(Any, object()))

    media = await gateway.download_media(StickerMessage(), assets_dir=tmp_path)

    assert media == [MediaRecord(kind="document", skipped_reason="sticker")]


async def test_iter_messages_uses_upper_bound_and_stops_after_since() -> None:
    messages = [
        FakeHistoryMessage(4, datetime(2026, 1, 2, 0, 0, tzinfo=UTC)),
        FakeHistoryMessage(5, datetime(2026, 1, 1, 16, 0, tzinfo=UTC)),
        FakeHistoryMessage(3, datetime(2026, 1, 1, 12, 0, tzinfo=UTC)),
        FakeHistoryMessage(2, datetime(2026, 1, 1, 1, 0, tzinfo=UTC)),
        FakeHistoryMessage(1, datetime(2025, 12, 31, 23, 59, tzinfo=UTC)),
        FakeHistoryMessage(0, datetime(2025, 1, 1, 0, 0, tzinfo=UTC)),
    ]
    client = FakeHistoryClient(messages)
    gateway = TelethonGateway(client=cast(Any, client))

    result: list[FakeHistoryMessage] = []
    async for message in gateway.iter_messages(
            object(),
            since=datetime(2026, 1, 1, 0, 0, tzinfo=UTC),
            until=datetime(2026, 1, 1, 16, 0, tzinfo=UTC),
    ):
        result.append(cast(FakeHistoryMessage, message))

    assert [message.id for message in result] == [3, 2]
    assert client.kwargs == {"offset_date": datetime(2026, 1, 1, 16, 0, tzinfo=UTC)}
    assert client.yielded == 5
