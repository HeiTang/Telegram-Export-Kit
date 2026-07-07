from __future__ import annotations

import json
from datetime import datetime, tzinfo
from pathlib import Path
from typing import Any, Literal

from jinja2 import Environment

from telegram_export_kit.jsonl import read_jsonl
from telegram_export_kit.utils import resolve_timezone

RenderFormat = Literal["html", "md"]


HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{{ title }}</title>
  <style>
    :root {
      color-scheme: light dark;
      --bg: #f4f6f8;
      --surface: #ffffff;
      --surface-muted: #f7f9fc;
      --border: #d7dee8;
      --text: #18202b;
      --muted: #647084;
      --muted-strong: #344054;
      --shadow: 0 1px 2px rgb(16 24 40 / 0.06);
      --accent: #476c9b;
      --accent-soft: #eef4fb;
      font-family:
        ui-sans-serif,
        system-ui,
        -apple-system,
        BlinkMacSystemFont,
        "Segoe UI",
        sans-serif;
    }
    body { margin: 0; background: var(--bg); color: var(--text); }
    main { max-width: 920px; margin: 0 auto; padding: 32px 18px 48px; }
    h1 {
      margin: 0 0 22px;
      color: #111827;
      font-size: 22px;
      font-weight: 750;
      letter-spacing: 0;
    }
    article {
      position: relative;
      border: 1px solid var(--border);
      border-left: 4px solid var(--accent);
      border-radius: 8px;
      padding: 13px 16px 14px;
      margin: 10px 0;
      background: var(--surface);
      box-shadow: var(--shadow);
    }
    .sender-c0 { --accent: #2563eb; --accent-soft: #eff6ff; }
    .sender-c1 { --accent: #059669; --accent-soft: #ecfdf5; }
    .sender-c2 { --accent: #7c3aed; --accent-soft: #f5f3ff; }
    .sender-c3 { --accent: #dc2626; --accent-soft: #fef2f2; }
    .sender-c4 { --accent: #0d9488; --accent-soft: #f0fdfa; }
    .sender-c5 { --accent: #b45309; --accent-soft: #fffbeb; }
    .sender-c6 { --accent: #4f46e5; --accent-soft: #eef2ff; }
    .sender-c7 { --accent: #db2777; --accent-soft: #fdf2f8; }
    .target {
      border-color: #8fb4ff;
      border-left-color: var(--accent);
      box-shadow: 0 0 0 2px rgb(37 99 235 / 0.12), var(--shadow);
    }
    .meta {
      display: flex;
      align-items: baseline;
      justify-content: space-between;
      gap: 16px;
      margin-bottom: 6px;
    }
    .sender {
      min-width: 0;
      max-width: 100%;
      color: #101828;
      font-size: 15px;
      font-weight: 750;
      line-height: 1.25;
      overflow-wrap: anywhere;
    }
    .timestamp {
      flex: 0 0 auto;
      border-radius: 6px;
      padding: 2px 6px;
      background: var(--surface-muted);
      color: var(--muted-strong);
      font-size: 12px;
      font-variant-numeric: tabular-nums;
      font-weight: 700;
      line-height: 1.2;
      white-space: nowrap;
    }
    .submeta {
      color: var(--muted);
      font-size: 12px;
      margin: -4px 0 8px;
    }
    .reply {
      border-left: 3px solid var(--accent);
      border-radius: 6px;
      margin: 8px 0 10px;
      padding: 7px 10px;
      background: var(--accent-soft);
      color: #27364a;
      font-size: 13px;
    }
    .reply a { color: inherit; font-weight: 600; text-decoration: none; }
    .reply .reply-text {
      margin-top: 2px;
      color: #586577;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .text { white-space: pre-wrap; line-height: 1.5; }
    .media { margin-top: 8px; font-size: 13px; }
    a { color: #1d4ed8; }
    @media (prefers-color-scheme: dark) {
      :root {
        --bg: #101319;
        --surface: #171b23;
        --surface-muted: #202734;
        --border: #2c3545;
        --text: #eef2f7;
        --muted: #9aa6b8;
        --muted-strong: #d7deea;
        --shadow: none;
      }
      h1 { color: #f8fafc; }
      .sender { color: #f8fafc; }
      .reply { background: rgb(255 255 255 / 0.04); color: #d9e2ee; }
      .reply .reply-text { color: #aeb9c8; }
      a { color: #8ab4ff; }
    }
    @media (max-width: 560px) {
      .meta {
        display: block;
      }
      .timestamp {
        display: inline-block;
        margin-top: 6px;
      }
      .submeta {
        margin-top: 6px;
      }
    }
  </style>
</head>
<body>
<main>
  <h1>{{ title }}</h1>
  {% for message in messages %}
  <article
    id="msg-{{ message.id }}"
    class="sender-c{{ message.sender_color }}{% if message.target_user_match %} target{% endif %}"
  >
    <div class="meta">
      <div class="sender">{{ message.sender }}</div>
      <time class="timestamp" datetime="{{ message.datetime }}">{{ message.date }}</time>
    </div>
    <div class="submeta">
      #{{ message.id }} · {{ message.context_kind }}
    </div>
    {% if message.reply %}
    <div class="reply">
      {% if message.reply.found %}
        <a href="#msg-{{ message.reply.id }}">
          ↩ Reply to #{{ message.reply.id }} · {{ message.reply.sender }}
        </a>
        {% if message.reply.text %}<div class="reply-text">{{ message.reply.text }}</div>{% endif %}
      {% else %}
        <span>↩ Reply to #{{ message.reply.id }} (not in this export)</span>
      {% endif %}
    </div>
    {% endif %}
    {% if message.text %}<div class="text">{{ message.text }}</div>{% endif %}
    {% for media in message.media %}
      <div class="media">
        {% if media.path %}
          <a href="{{ media.path }}">{{ media.file_name or media.path }}</a>
        {% else %}
          {{ media.kind }} skipped: {{ media.skipped_reason }}
        {% endif %}
      </div>
    {% endfor %}
  </article>
  {% endfor %}
</main>
</body>
</html>
"""


def render(
    input_path: Path,
    *,
    output_path: Path | None = None,
    fmt: RenderFormat,
    timezone: str | None = None,
) -> Path:
    raw_messages = list(read_jsonl(input_path))
    display_timezone = resolve_timezone(timezone or _manifest_timezone(input_path))
    messages = _display_records(raw_messages, timezone=display_timezone)
    output = output_path or input_path.with_suffix(f".{fmt}")
    output.parent.mkdir(parents=True, exist_ok=True)

    if fmt == "html":
        content = _render_html(messages, title=input_path.parent.name or "Telegram export")
    elif fmt == "md":
        content = _render_markdown(messages, title=input_path.parent.name or "Telegram export")
    else:
        raise ValueError(f"Unsupported render format: {fmt}")

    output.write_text(content, encoding="utf-8")
    return output


def _manifest_timezone(input_path: Path) -> str | None:
    manifest_path = input_path.with_name("manifest.json")
    if not manifest_path.exists():
        return None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    timezone = manifest.get("timezone")
    return timezone if isinstance(timezone, str) and timezone else None


def _display_records(records: list[dict[str, Any]], *, timezone: tzinfo) -> list[dict[str, Any]]:
    displayed = [_display_record(item, timezone=timezone) for item in records]
    by_id = {item["id"]: item for item in displayed}
    for item in displayed:
        reply_to_msg_id = item["reply_to_msg_id"]
        if reply_to_msg_id is None:
            continue
        replied = by_id.get(reply_to_msg_id)
        item["reply"] = {
            "id": reply_to_msg_id,
            "found": replied is not None,
            "sender": replied["sender"] if replied else "",
            "text": _summarize_reply(replied["text"] if replied else ""),
        }
    return displayed


def _display_record(record: dict[str, Any], *, timezone: tzinfo) -> dict[str, Any]:
    sender = record.get("sender") or {}
    display_name = (
        sender.get("display_name") or sender.get("username") or sender.get("id") or "unknown"
    )
    sender_key = str(sender.get("id") or sender.get("username") or display_name)
    media = record.get("media") or []
    return {
        "id": record.get("id"),
        "datetime": _format_datetime_attr(record.get("date")),
        "date": _format_date(record.get("date"), timezone=timezone),
        "sender": str(display_name),
        "sender_color": _stable_color_index(sender_key),
        "text": record.get("text") or "",
        "media": media,
        "reply_to_msg_id": record.get("reply_to_msg_id"),
        "reply": None,
        "context_kind": record.get("context_kind"),
        "target_user_match": record.get("sender_match", record.get("target_user_match", False)),
    }


def _render_html(messages: list[dict[str, Any]], *, title: str) -> str:
    env = Environment(autoescape=True)
    template = env.from_string(HTML_TEMPLATE)
    return template.render(title=title, messages=messages)


def _render_markdown(messages: list[dict[str, Any]], *, title: str) -> str:
    lines = [f"# {title}", ""]
    for message in messages:
        lines.append(
            f"## #{message['id']} - {message['date']} - "
            f"{message['sender']} - {message['context_kind']}"
        )
        lines.append("")
        if message["reply"]:
            reply = message["reply"]
            if reply["found"]:
                lines.append(
                    f"> Reply to [#{reply['id']}](#msg-{reply['id']}) · {reply['sender']}"
                )
                if reply["text"]:
                    lines.append(f"> {reply['text']}")
            else:
                lines.append(f"> Reply to #{reply['id']} (not in this export)")
            lines.append("")
        if message["text"]:
            lines.append(_unescape_basic(message["text"]))
            lines.append("")
        for media in message["media"]:
            if media.get("path"):
                label = media.get("file_name") or media["path"]
                lines.append(f"- [{label}]({media['path']})")
            else:
                lines.append(
                    f"- {media.get('kind', 'media')} skipped: {media.get('skipped_reason')}"
                )
        if message["media"]:
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _format_date(value: str | None, *, timezone: tzinfo) -> str:
    if not value:
        return ""
    try:
        return (
            datetime.fromisoformat(value.replace("Z", "+00:00"))
            .astimezone(timezone)
            .strftime("%Y-%m-%d %H:%M:%S")
        )
    except ValueError:
        return value


def _format_datetime_attr(value: str | None) -> str:
    if not value:
        return ""
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).isoformat()
    except ValueError:
        return value


def _unescape_basic(value: str) -> str:
    return value.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")


def _summarize_reply(value: str, *, limit: int = 120) -> str:
    text = " ".join(value.split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _stable_color_index(value: str, *, palette_size: int = 8) -> int:
    return sum(value.encode("utf-8")) % palette_size
