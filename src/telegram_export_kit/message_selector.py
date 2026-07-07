from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from telegram_export_kit.models import ContextKind
from telegram_export_kit.slicing import classify_context, indexes_from_windows, merge_windows

ExportMode = Literal["private", "group_slice", "full_chat"]


@dataclass(frozen=True)
class MessageSelection:
    selected_indexes: set[int]
    context_by_index: dict[int, ContextKind]
    target_indexes: set[int]
    mode: ExportMode

    @property
    def selected_count(self) -> int:
        return len(self.selected_indexes)

    @property
    def target_count(self) -> int:
        return len(self.target_indexes)


def select_messages(
    messages: Sequence[Any],
    *,
    is_private: bool,
    target_sender_id: int | None,
    sender_id_for: Callable[[Any], int | None],
    window_before: int,
    window_after: int,
) -> MessageSelection:
    target_indexes = {
        index
        for index, message in enumerate(messages)
        if target_sender_id is not None and sender_id_for(message) == target_sender_id
    }

    if is_private:
        selected_indexes = set(range(len(messages)))
        return MessageSelection(
            selected_indexes=selected_indexes,
            context_by_index={index: "private" for index in selected_indexes},
            target_indexes=target_indexes,
            mode="private",
        )

    if target_sender_id is None:
        selected_indexes = set(range(len(messages)))
        return MessageSelection(
            selected_indexes=selected_indexes,
            context_by_index={index: "target" for index in selected_indexes},
            target_indexes=target_indexes,
            mode="full_chat",
        )

    windows = merge_windows(
        target_indexes,
        before=window_before,
        after=window_after,
        total=len(messages),
    )
    selected_indexes = indexes_from_windows(windows)
    return MessageSelection(
        selected_indexes=selected_indexes,
        context_by_index={
            index: classify_context(index, target_indexes) for index in selected_indexes
        },
        target_indexes=target_indexes,
        mode="group_slice",
    )
