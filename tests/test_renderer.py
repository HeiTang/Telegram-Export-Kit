from pathlib import Path

from telegram_export_kit.jsonl import append_jsonl
from telegram_export_kit.renderer import render


def test_render_markdown_and_html(tmp_path: Path) -> None:
    jsonl = tmp_path / "messages.jsonl"
    append_jsonl(
        jsonl,
        {
            "id": 1,
            "date": "2026-01-01T00:00:00+00:00",
            "sender": {"display_name": "Alice"},
            "text": "hello <world>",
            "context_kind": "target",
            "target_user_match": True,
            "media": [{"path": "assets/a.jpg", "file_name": "a.jpg", "kind": "photo"}],
        },
    )
    append_jsonl(
        jsonl,
        {
            "id": 2,
            "date": "2026-01-01T00:01:00+00:00",
            "sender": {"display_name": "Bob"},
            "text": "reply text",
            "reply_to_msg_id": 1,
            "context_kind": "target",
            "target_user_match": False,
            "media": [],
        },
    )

    md = render(jsonl, fmt="md", timezone="Asia/Taipei")
    html = render(jsonl, fmt="html", timezone="Asia/Taipei")
    html_text = html.read_text()
    md_text = md.read_text()

    assert md.exists()
    assert html.exists()
    assert "hello <world>" in md_text
    assert "Reply to [#1]" in md_text
    assert "(#msg-1)" in md_text
    assert 'id="msg-1"' in html_text
    assert 'class="sender-c' in html_text
    assert 'class="sender"' in html_text
    assert 'class="timestamp"' in html_text
    assert "2026-01-01 08:00:00" in html_text
    assert 'href="#msg-1"' in html_text
    assert "assets/a.jpg" in html_text


def test_render_uses_manifest_timezone(tmp_path: Path) -> None:
    jsonl = tmp_path / "messages.jsonl"
    (tmp_path / "manifest.json").write_text('{"timezone": "Asia/Taipei"}')
    append_jsonl(
        jsonl,
        {
            "id": 1,
            "date": "2026-01-01T00:00:00+00:00",
            "sender": {"display_name": "Alice"},
            "text": "hello",
            "context_kind": "private",
            "media": [],
        },
    )

    html = render(jsonl, fmt="html")

    assert "2026-01-01 08:00:00" in html.read_text()
