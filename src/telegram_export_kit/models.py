from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ContextKind = Literal["private", "target", "before", "after"]
MediaKind = Literal["photo", "document", "video", "audio", "voice", "unknown"]


class ChatRecord(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: int
    title: str | None = None
    username: str | None = None
    type: Literal["private", "group", "channel", "unknown"] = "unknown"


class SenderRecord(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: int | None = None
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    display_name: str | None = None
    is_bot: bool | None = None
    is_self: bool | None = None


class MediaRecord(BaseModel):
    model_config = ConfigDict(extra="allow")

    kind: MediaKind
    path: str | None = None
    file_name: str | None = None
    mime_type: str | None = None
    size: int | None = None
    skipped_reason: str | None = None


class MessageRecord(BaseModel):
    model_config = ConfigDict(extra="allow")

    export_version: int = 1
    chat: ChatRecord
    id: int
    date: datetime
    sender: SenderRecord | None = None
    text: str | None = None
    entities: list[dict[str, Any]] = Field(default_factory=list)
    reply_to_msg_id: int | None = None
    forward: dict[str, Any] | None = None
    grouped_id: int | None = None
    edit_date: datetime | None = None
    media: list[MediaRecord] = Field(default_factory=list)
    context_kind: ContextKind
    sender_match: bool = False
    target_user_match: bool = False
    source: dict[str, Any] = Field(default_factory=dict)


class ExportManifest(BaseModel):
    model_config = ConfigDict(extra="allow")

    export_version: int = 1
    id: str | None = None
    uuid: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    chat: ChatRecord
    target_sender: SenderRecord | None = None
    mode: Literal["private", "group_slice", "full_chat"]
    since: datetime | None = None
    until: datetime | None = None
    timezone: str | None = None
    window_before: int
    window_after: int
    download_media: bool
    source: dict[str, Any] = Field(default_factory=dict)
    path_key: str | None = None
    criteria_hash: str | None = None
    messages_path: str = "messages.jsonl"
    assets_path: str = "assets"
    stats: dict[str, int] = Field(default_factory=dict)
    runs: list[dict[str, Any]] = Field(default_factory=list)


class ExportOptions(BaseModel):
    chat: str
    sender: str | None = None
    out_dir: Path
    since: datetime | None = None
    until: datetime | None = None
    timezone: str | None = None
    window_before: int = Field(default=20, ge=0)
    window_after: int = Field(default=20, ge=0)
    download_media: bool = True
    update_media: bool = True
    dry_run: bool = False
    resume: bool = True
    export_id: str | None = None
    export_uuid: str | None = None
    source: dict[str, Any] = Field(default_factory=dict)
    path_key: str | None = None
    criteria_hash: str | None = None
