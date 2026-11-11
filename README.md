# Telegram Export Kit

Local-first CLI toolkit for exporting, validating, searching, rendering, and
packaging Telegram conversations.

It exports Telegram private chats, whole group chats, or group messages around a
selected sender into local files:

- `messages.jsonl`: canonical message data
- `assets/`: downloaded media
- `manifest.json`: export identity, criteria, labels, and run history

After export, most commands work locally. Search, verify, and render do not
connect to Telegram again.

## Quickstart

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

Log in:

```bash
uv run tg-export auth login
```

Find chats:

```bash
uv run tg-export dialogs list
```

Export a private chat:

```bash
uv run tg-export export --chat alice --date 2026-07-01
```

List exports and keep the ID:

```bash
uv run tg-export exports list
```

Search, render, and verify the newest export:

```bash
uv run tg-export search --latest --query "payment"
uv run tg-export render html --latest
uv run tg-export verify --latest
```

For repeatable commands, prefer a stable export ID:

```bash
uv run tg-export search --export 8f3a2c91 --query "payment"
uv run tg-export render md --export 8f3a2c91
uv run tg-export verify --export 8f3a2c91
```

Need Telegram credentials? See [docs/SETUP.md](docs/SETUP.md).

## Export Modes

### Private chat

Exports the dialog with one user. You do not need `--sender`.

```bash
uv run tg-export export --chat alice --date 2026-07-01
```

### Whole group

Exports all visible group messages in the date range.

```bash
uv run tg-export export --chat project_group --date 2026-07-01
```

### Group context around one sender

Exports messages sent by one sender plus surrounding context. This is useful
when you want "what happened around Alice's messages" instead of the whole group.

```bash
uv run tg-export export \
  --chat project_group \
  --sender alice \
  --date 2026-07-01 \
  --window-before 20 \
  --window-after 20
```

Overlapping windows are merged. Images and files are downloaded into `assets/`
unless `--no-media` is set. Stickers are recorded in JSONL metadata but are not
downloaded.

## Dates

Use `--date` for one local calendar day:

```bash
uv run tg-export export --chat alice --date 2026-07-01
```

Use `--start-date` and `--end-date` for a local whole-day range:

```bash
uv run tg-export export \
  --chat alice \
  --start-date 2026-07-01 \
  --end-date 2026-07-31
```

Date filters use the selected timezone, then convert to a UTC half-open range:

```text
since <= message < until
```

With `TG_TIMEZONE=Asia/Taipei`, `--date 2026-07-01` scans:

```text
2026-06-30T16:00:00+00:00 <= message < 2026-07-01T16:00:00+00:00
```

Prefer an IANA timezone such as `Asia/Taipei`. `UTC+8`, `UTC+08:00`, and
`+08:00` are also accepted.

## Reading Existing Exports

Once an export exists, local commands need to know which export to read.

Use exactly one selector:

| Selector | Use when | Example |
| --- | --- | --- |
| `--latest` | You are exploring the newest export. | `uv run tg-export search --latest --query "payment"` |
| `--export ID` | You want a stable, repeatable command. | `uv run tg-export render html --export 8f3a2c91` |
| `INPUT_PATH` | You are scripting, debugging, or reading an archived path directly. | `uv run tg-export verify exports/private__u7035465201/2026-07-01` |

These commands all use the same three valid shapes:

```bash
# Newest export.
uv run tg-export search --latest

# A stable export ID from `exports list`.
uv run tg-export search --export 8f3a2c91

# A direct export directory or messages.jsonl path.
uv run tg-export search exports/private__u7035465201/2026-07-01
```

Only one selector is allowed because `--latest`, `--export ID`, and `INPUT_PATH`
can point to different exports. The command refuses ambiguous input instead of
guessing.

The same selector rule applies to `search`, `verify`, `render html`, and
`render md`.

When unsure, run:

```bash
uv run tg-export exports list
```

Then use the ID:

```bash
uv run tg-export search --export 8f3a2c91 --query "payment"
```

## Search

Search reads local `messages.jsonl`; it does not connect to Telegram.

```bash
uv run tg-export search --latest --query "payment"
uv run tg-export search --export 8f3a2c91 --sender alice
uv run tg-export search --export 8f3a2c91 --has-media --format jsonl
```

For group context exports:

```bash
# Messages sent by the selected sender.
uv run tg-export search --export 8f3a2c91 --context target

# Context messages before the selected sender's messages.
uv run tg-export search --export 8f3a2c91 --context before
```

For whole-group exports, every row currently uses `context=target` because there
is no separate selected sender. Use `--sender`, `--query`, `--from`, `--to`, or
`--has-media` when searching whole-group exports.

For private exports, messages use `context=private`, not `context=target`.
Use `--target-only` when you want only the other person's messages:

```bash
uv run tg-export search --export 8f3a2c91 --target-only
```

## Render

Render turns the canonical JSONL into a readable file.

```bash
uv run tg-export render html --latest
uv run tg-export render md --export 8f3a2c91
```

Default output:

- HTML: `messages.html`
- Markdown: `messages.md`

Use Markdown when you want a text version for Obsidian or reports. Use HTML when
you want a standalone readable conversation view.

## Verify And Repair

Verify one export:

```bash
uv run tg-export verify --latest
uv run tg-export verify --export 8f3a2c91
```

Check the export registry:

```bash
uv run tg-export exports doctor
```

`exports/.index.json` is only a rebuildable cache. If it becomes stale after
manual file moves, rebuild it from manifests:

```bash
uv run tg-export exports rebuild-index
uv run tg-export exports doctor
```

## Updating An Existing Export

If the same export criteria already exists, the default is to stop and print the
existing ID and path.

Pick one explicit action:

```bash
# Resume non-destructively: skip existing ids and fill missing media.
uv run tg-export export --chat project_group --sender alice --date 2026-07-01 --update

# Rebuild safely: verify replacement data before replacing the old payload.
uv run tg-export export --chat project_group --sender alice --date 2026-07-01 --overwrite

# Create a sibling export with a new ID.
uv run tg-export export --chat project_group --sender alice --date 2026-07-01 --new
```

Use `--update` first unless you intentionally want a clean rebuild.

Updates retain previously saved messages even if they disappear from Telegram.
The manifest's `stats.selected` and export list show the saved message count;
each entry in `runs` records that run's selection count. Zero-message exports
remain valid and searchable.

Existing output directories must belong to the same export, including with
`--flat`. `--flat --new` creates an `export__ID` subdirectory inside `--out`, so
moving the root and rebuilding its index keeps both exports discoverable.

`--overwrite` keeps the old payload until the replacement passes verification.
Run only one writer per export. For recovery after a forced termination, see
[Overwrite Recovery](docs/EXPORT_MODEL.md#overwrite-recovery).

## Output Layout

Default exports are ID-first and stable. Usernames, group titles, and display
names are stored in `manifest.json` and shown by `exports list`, but they are not
used as the path contract.

```text
exports/private__u7035465201/2026-07-01/
exports/group__c-1001234567890__u777000/2026-07-01/
exports/group__c-1001234567890__all/2026-07-01/
```

Inside each export:

```text
messages.jsonl
assets/
manifest.json
```

For the full path, manifest, index, and ID rules, see
[docs/EXPORT_MODEL.md](docs/EXPORT_MODEL.md).

## More Docs

- [docs/SETUP.md](docs/SETUP.md): Telegram API credentials and local setup.
- [docs/CLI_REFERENCE.md](docs/CLI_REFERENCE.md): complete command options.
- [docs/EXPORT_MODEL.md](docs/EXPORT_MODEL.md): export identity, path, manifest, and index model.
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): module boundaries and design rules.
- [docs/RELEASE_CHECKLIST.md](docs/RELEASE_CHECKLIST.md): RC validation checklist.

## Release Checks

```bash
uv run pytest
uv run ruff check .
uv run mypy src tests
uv run tg-export exports doctor
uv build
```
