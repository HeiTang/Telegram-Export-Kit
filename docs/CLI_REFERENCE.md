# CLI Reference

This file is the detailed option reference. For the normal learning path, start
with [README.md](../README.md).

## Selector Pattern

Commands that read an existing export accept the same selector pattern.

```bash
tg-export search [INPUT_PATH] [--latest] [--export ID] [--exports-root PATH]
tg-export verify [INPUT_PATH] [--latest] [--export ID] [--exports-root PATH]
tg-export render html [INPUT_PATH] [--latest] [--export ID] [--exports-root PATH]
tg-export render md [INPUT_PATH] [--latest] [--export ID] [--exports-root PATH]
```

Exactly one of `INPUT_PATH`, `--latest`, or `--export ID` must be provided.
`--exports-root PATH` only changes where `--latest` and `--export ID` look.

## `tg-export auth login`

Logs in with Telethon and writes a local session file.

| Option | Default | Description |
| --- | --- | --- |
| `--env-file PATH` | `.env` | Load Telegram credentials from this env file. |

## `tg-export dialogs list`

Lists Telegram dialogs visible to the logged-in account.

| Option | Default | Description |
| --- | --- | --- |
| `--env-file PATH` | `.env` | Load Telegram credentials from this env file. |
| `--limit INTEGER` | `100` | Maximum dialogs to list. |

## `tg-export export`

Exports a private chat, a whole group, or group context slices.

| Option | Required | Default | Description |
| --- | --- | --- | --- |
| `--chat TEXT` | Yes | - | Chat id, username, phone, or resolvable Telegram entity. |
| `--sender TEXT` | No | - | Optional sender id, username, or phone filter. If omitted, group exports include all senders. |
| `--out PATH` | No | `exports` | Export root directory. A scoped subdirectory is created by default. |
| `--date YYYY-MM-DD` | No | - | Export one local calendar day. Cannot be mixed with other date/time range options. |
| `--start-date YYYY-MM-DD` | No | - | Export range start date. Must be used with `--end-date`. |
| `--end-date YYYY-MM-DD` | No | - | Export range end date. Must be used with `--start-date`. |
| `--timezone TEXT` | No | `TG_TIMEZONE` or local timezone | Timezone used to interpret date filters, e.g. `Asia/Taipei` or `UTC+8`. |
| `--window-before INTEGER` | No | `20` | Group mode: messages before each target message. |
| `--window-after INTEGER` | No | `20` | Group mode: messages after each target message. |
| `--no-media` | No | `false` | Do not download images or files. |
| `--dry-run` | No | `false` | Count matching messages without writing output. |
| `--no-resume` | No | `false` | Ignore existing `messages.jsonl` and do not skip already-exported ids. |
| `--flat` | No | `false` | Write directly into `--out` instead of creating a scoped subdirectory. |
| `--update` | No | `false` | Reuse the same export ID and non-destructively resume an existing export with identical criteria. |
| `--overwrite` | No | `false` | Reuse the same export ID and destructively rebuild an existing export with identical criteria. |
| `--new` | No | `false` | Force a new export ID and sibling directory when criteria or path would collide. |
| `--env-file PATH` | No | `.env` | Load Telegram credentials from this env file. |

## `tg-export exports list`

Lists known exports from `exports/.index.json`.

| Option | Default | Description |
| --- | --- | --- |
| `--root PATH` | `exports` | Export root directory. |

## `tg-export exports rebuild-index`

Rebuilds `exports/.index.json` from export manifests. The index is a cache;
`manifest.json` remains the source of truth.

| Option | Default | Description |
| --- | --- | --- |
| `--root PATH` | `exports` | Export root directory. |

## `tg-export exports doctor`

Checks export registry consistency.

| Option | Default | Description |
| --- | --- | --- |
| `--root PATH` | `exports` | Export root directory. |

## `tg-export search`

Searches local `messages.jsonl`. It does not connect to Telegram.

| Argument / Option | Required | Default | Description |
| --- | --- | --- | --- |
| `INPUT_PATH` | No | - | Export directory or path to `messages.jsonl`. |
| `--latest` | No | `false` | Use the newest export. |
| `--export TEXT` | No | - | Use a stable export ID from `exports list`. |
| `--exports-root PATH` | No | `exports` | Root used by `--latest` and `--export`. |
| `--query TEXT` | No | - | Text query. |
| `--sender TEXT` | No | - | Sender id, username, or display name. |
| `--from YYYY-MM-DD` | No | - | Start local date. |
| `--to YYYY-MM-DD` | No | - | End local date. |
| `--context TEXT` | No | - | Filter by message context: `private`, `target`, `before`, or `after`. |
| `--target-only` | No | `false` | Only messages sent by the export target. |
| `--has-media` | No | `false` | Only rows with media. |
| `--limit INTEGER` | No | - | Maximum result count. |
| `--timezone TEXT` | No | `TG_TIMEZONE` or local timezone | Timezone used to interpret date filters. |
| `--format table\|jsonl\|md` | No | `table` | Output format. |

## `tg-export verify`

Checks JSONL parsing, required message fields, duplicate ids, asset paths, reply
targets, sort order, and the `manifest.json` contract.

| Argument / Option | Required | Default | Description |
| --- | --- | --- | --- |
| `INPUT_PATH` | No | - | Export directory or path to `messages.jsonl`. |
| `--latest` | No | `false` | Use the newest export. |
| `--export TEXT` | No | - | Use a stable export ID from `exports list`. |
| `--exports-root PATH` | No | `exports` | Root used by `--latest` and `--export`. |

## `tg-export render html`

Converts `messages.jsonl` into a standalone HTML file.

| Argument / Option | Required | Default | Description |
| --- | --- | --- | --- |
| `INPUT_PATH` | No | - | Export directory or path to `messages.jsonl`. |
| `--latest` | No | `false` | Use the newest export. |
| `--export TEXT` | No | - | Use a stable export ID from `exports list`. |
| `--exports-root PATH` | No | `exports` | Root used by `--latest` and `--export`. |
| `--out PATH` | No | `INPUT_PATH` with `.html` suffix | Output HTML path. |
| `--timezone TEXT` | No | manifest `timezone`, `TG_TIMEZONE`, or local timezone | Timezone used to display timestamps. |
| `--env-file PATH` | No | `.env` | Load `TG_TIMEZONE` from this env file. |

## `tg-export render md`

Converts `messages.jsonl` into Markdown.

| Argument / Option | Required | Default | Description |
| --- | --- | --- | --- |
| `INPUT_PATH` | No | - | Export directory or path to `messages.jsonl`. |
| `--latest` | No | `false` | Use the newest export. |
| `--export TEXT` | No | - | Use a stable export ID from `exports list`. |
| `--exports-root PATH` | No | `exports` | Root used by `--latest` and `--export`. |
| `--out PATH` | No | `INPUT_PATH` with `.md` suffix | Output Markdown path. |
| `--timezone TEXT` | No | manifest `timezone`, `TG_TIMEZONE`, or local timezone | Timezone used to display timestamps. |
| `--env-file PATH` | No | `.env` | Load `TG_TIMEZONE` from this env file. |

## `tg-export members list`

Lists members visible to the current account for a group.

| Option | Default | Description |
| --- | --- | --- |
| `--chat TEXT` | - | Group id or username. |
| `--limit INTEGER` | - | Maximum members to list. |
| `--search TEXT` | - | Search members by name. |
| `--env-file PATH` | `.env` | Load Telegram credentials from this env file. |

## `tg-export senders list`

Lists users who sent messages in recent chat history.

| Option | Default | Description |
| --- | --- | --- |
| `--chat TEXT` | - | Chat id or username. |
| `--limit INTEGER` | `5000` | Number of recent messages to scan. |
| `--env-file PATH` | `.env` | Load Telegram credentials from this env file. |
