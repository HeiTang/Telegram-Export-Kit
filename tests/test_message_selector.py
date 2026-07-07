from __future__ import annotations

from dataclasses import dataclass

from telegram_export_kit.message_selector import select_messages


@dataclass(frozen=True)
class Message:
    sender_id: int


def _sender_id(message: Message) -> int:
    return message.sender_id


def test_select_messages_for_group_slice_merges_context_windows() -> None:
    messages = [
        Message(1),
        Message(1),
        Message(7),
        Message(2),
        Message(7),
        Message(3),
    ]

    selection = select_messages(
        messages,
        is_private=False,
        target_sender_id=7,
        sender_id_for=_sender_id,
        window_before=1,
        window_after=1,
    )

    assert selection.mode == "group_slice"
    assert selection.target_indexes == {2, 4}
    assert selection.selected_indexes == {1, 2, 3, 4, 5}
    assert [selection.context_by_index[index] for index in sorted(selection.selected_indexes)] == [
        "before",
        "target",
        "after",
        "target",
        "after",
    ]


def test_select_messages_for_private_chat_keeps_private_context() -> None:
    selection = select_messages(
        [Message(1), Message(7)],
        is_private=True,
        target_sender_id=7,
        sender_id_for=_sender_id,
        window_before=0,
        window_after=0,
    )

    assert selection.mode == "private"
    assert selection.selected_indexes == {0, 1}
    assert set(selection.context_by_index.values()) == {"private"}
