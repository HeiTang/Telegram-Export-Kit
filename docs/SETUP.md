# Setup

## Install

```bash
uv sync
cp .env.example .env
```

Fill `.env`:

```env
TG_API_ID=12345678
TG_API_HASH=abcdef0123456789abcdef0123456789
TG_PHONE=+8869xxxxxxxx
TG_SESSION=.sessions/tg-export
TG_TIMEZONE=Asia/Taipei
```

## Telegram API Credentials

Get `TG_API_ID` and `TG_API_HASH` from Telegram:

1. Open <https://my.telegram.org/apps>.
2. Log in with your Telegram phone number, for example `+8869xxxxxxxx`.
3. Enter the confirmation code sent to your Telegram app.
4. Open `API development tools`.
5. Create an app:
   - `App title`: `Telegram Export Kit`
   - `Short name`: `tg_exporter`
   - `Platform`: `Desktop`
   - `Description`: `Personal Telegram chat export tool`
6. Copy `api_id` to `TG_API_ID`.
7. Copy `api_hash` to `TG_API_HASH`.

You can reuse an existing `api_id` / `api_hash` from another Telegram API tool.
Do not reuse another tool's `.session` file unless it is also Telethon and you
know both tools will not run at the same time.

Do not commit `.env`, `.sessions/`, or exported chat data.

## Login

```bash
uv run tg-export auth login
```

## Timezone

Set `TG_TIMEZONE` to the timezone you want date filters and rendered timestamps
to use:

```env
TG_TIMEZONE=Asia/Taipei
```

You can override it per command:

```bash
uv run tg-export export --chat alice --date 2026-07-01 --timezone Asia/Taipei
```

Prefer an IANA timezone such as `Asia/Taipei`. `UTC+8`, `UTC+08:00`, and
`+08:00` are also accepted.
