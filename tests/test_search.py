from pathlib import Path

from telegram_export_kit.jsonl import append_jsonl
from telegram_export_kit.search import search_messages


def _write_messages(path: Path) -> None:
    append_jsonl(
        path,
        {
            "id": 1,
            "date": "2026-01-01T00:00:00+00:00",
            "sender": {"id": 10, "username": "alice", "display_name": "Alice"},
            "text": "Payment was sent yesterday",
            "context_kind": "target",
            "sender_match": True,
            "target_user_match": True,
            "media": [],
        },
    )
    append_jsonl(
        path,
        {
            "id": 2,
            "date": "2026-01-02T00:00:00+00:00",
            "sender": {"id": 11, "username": "bob", "display_name": "Bob"},
            "text": "receipt photo",
            "context_kind": "after",
            "sender_match": False,
            "target_user_match": False,
            "media": [{"kind": "photo", "path": "assets/receipt.jpg"}],
        },
    )


def test_search_filters_by_query_sender_and_context(tmp_path: Path) -> None:
    jsonl = tmp_path / "messages.jsonl"
    _write_messages(jsonl)

    results = search_messages(jsonl, query="payment", sender="alice", context="target")

    assert [result.id for result in results] == [1]
    assert results[0].sender == "Alice"
    assert results[0].anchor == "messages.html#msg-1"
    assert "Payment" in results[0].snippet


def test_search_filters_by_media_and_date(tmp_path: Path) -> None:
    jsonl = tmp_path / "messages.jsonl"
    (tmp_path / "manifest.json").write_text('{"timezone": "UTC"}')
    _write_messages(jsonl)

    results = search_messages(jsonl, date_from="2026-01-02", date_to="2026-01-02", has_media=True)

    assert [result.id for result in results] == [2]
    assert results[0].media_count == 1


def test_search_limit_stops_after_requested_count(tmp_path: Path) -> None:
    jsonl = tmp_path / "messages.jsonl"
    _write_messages(jsonl)

    results = search_messages(jsonl, limit=1)

    assert [result.id for result in results] == [1]


def test_search_accepts_export_directory(tmp_path: Path) -> None:
    jsonl = tmp_path / "messages.jsonl"
    _write_messages(jsonl)

    results = search_messages(tmp_path, query="receipt")

    assert [result.id for result in results] == [2]


def test_search_filters_target_only_independent_of_context(tmp_path: Path) -> None:
    jsonl = tmp_path / "messages.jsonl"
    _write_messages(jsonl)

    results = search_messages(jsonl, target_only=True)

    assert [result.id for result in results] == [1]
