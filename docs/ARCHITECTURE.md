# Architecture

This project is a CLI-first Telegram export tool. The standard architecture is:

- domain logic is isolated from CLI wiring
- `messages.jsonl` is the canonical message store
- `manifest.json` is the canonical export metadata store
- `exports/.index.json` is only a rebuildable lookup cache
- physical paths are stable user-facing conveniences, not identity

## Module Boundaries

| Module | Responsibility |
| --- | --- |
| `cli.py` | Typer commands, terminal output, process exit behavior. |
| `export_plan.py` | Export identity, path planning, duplicate policy, update/overwrite/new decisions. |
| `export_index.py` | Discover, rebuild, validate, and resolve export registry data. |
| `exporter.py` | Export orchestration: resolve entities, scan messages, call selector/media/manifest helpers. |
| `message_selector.py` | Select private/full-chat/group-slice messages and assign context roles. |
| `media_exporter.py` | Read existing JSONL records and refill skipped or missing media. |
| `manifest_writer.py` | Preserve and update export manifests and run history. |
| `gateway.py` | Telegram gateway protocol used by exporter tests and implementations. |
| `telethon_gateway.py` | Telethon-specific adapter. No export policy should live here. |
| `search.py` | Local JSONL search only. It does not connect to Telegram. |
| `verify.py` | Local export integrity checks. |
| `renderer.py` | JSONL to HTML/Markdown presentation. |
| `models.py` | Shared typed data contracts. |

The CLI should compose modules. It should not own export identity, path naming,
registry mutation, or message slicing rules.

## Export Identity

Each export has two identifiers:

- `id`: short stable ID for humans and CLI usage, for example `fb884eb1`
- `uuid`: full UUID for durable internal identity

The user-facing lookup contract is:

```bash
uv run tg-export exports list
uv run tg-export search --export fb884eb1 --query "payment"
uv run tg-export verify --export fb884eb1
```

There is no positional `--export 1` behavior. Positional indexes are unstable
when exports are added, deleted, rebuilt, or sorted differently.

## Manifest Is Source Of Truth

Every export directory owns its identity and criteria through `manifest.json`.
The registry at `exports/.index.json` exists for fast lookup and list rendering
only. It must always be possible to delete and rebuild `.index.json` from
manifests:

```bash
uv run tg-export exports rebuild-index
uv run tg-export exports doctor
```

`manifest.json` must already include:

- `id`
- `uuid`
- `path_key`
- `criteria_hash`

`exports rebuild-index` does not mutate manifests. If an export manifest is
missing identity fields, the export is invalid and `exports doctor` must report
an error.

## Path Key And Criteria Hash

Two hashes serve different purposes.

`path_key` is the stable physical grouping key:

- resolved chat ID
- resolved target ID, if any
- date scope

`criteria_hash` is the exact semantic export key:

- mode: `private`, `group_slice`, or `full_chat`
- chat identity
- target identity
- time range
- timezone
- context window for `group_slice`
- media policy when it changes output semantics

`window_before` and `window_after` belong in `criteria_hash` for group slices,
because changing them changes the exported message set. They do not belong in
the default physical path, because the path should stay readable and stable.
When the same `path_key` has different criteria, the default behavior is to stop
and ask for an explicit action.

## Physical Path Contract

Default export layout:

```text
exports/
└── scope_key/
    └── date_scope/
        ├── messages.jsonl
        ├── assets/
        └── manifest.json
```

Examples:

```text
exports/private__u7035465201/2026-07-01/
exports/group__c-1001234567890__u777000/2026-01-01_to_2026-01-31/
exports/group__c-1001234567890__all/2026-01-01_to_2026-01-31/
```

Path scope keys must be based on resolved Telegram IDs, not raw CLI input,
username, group title, or display name. This prevents the same chat from creating
different directories when invoked by ID, username, or phone number, and prevents
renames from changing the physical path.

Scope key formats:

| Export kind | Scope key |
| --- | --- |
| Private chat | `private__u<user_id>` |
| Group slice | `group__c<chat_id>__u<target_id>` |
| Full group | `group__c<chat_id>__all` |

Human-readable labels belong in `manifest.json` and `exports list`. The path is
a stable convenience. Export identity comes from `manifest.json`.

## Existing Export Policy

For the same `criteria_hash`:

- default: fail with the existing ID and path
- `--update`: reuse ID/path and resume non-destructively
- `--overwrite`: reuse ID/path and rebuild payload destructively
- `--new`: create a new ID and sibling path

For the same `path_key` but different `criteria_hash`:

- default: fail because the readable path would collide
- `--new`: create a sibling path with the new ID suffix

This avoids silent overwrites and keeps CLI behavior explicit before RC.

## Local Command Selector Contract

Commands that read an existing export should share the same selector shape:

```text
tg-export search [INPUT_PATH] [--latest] [--export ID] [--exports-root PATH]
tg-export verify [INPUT_PATH] [--latest] [--export ID] [--exports-root PATH]
tg-export render html [INPUT_PATH] [--latest] [--export ID] [--exports-root PATH]
tg-export render md [INPUT_PATH] [--latest] [--export ID] [--exports-root PATH]
```

Exactly one of `INPUT_PATH`, `--latest`, or `--export ID` must be provided.
`INPUT_PATH` is kept for scripts and power users. `--export ID` is the preferred
human workflow because users should not have to remember physical paths.

## Incremental Updates

Current `--update` behavior is idempotent resume:

- skip already exported message IDs
- append missing messages
- fill missing media when possible
- preserve the existing export ID
- record another run in `manifest.json`

Bounded `--date`, `--start-date`, and `--end-date` exports use the same model:
the manifest records the criteria, and updates are only considered the same
export when the criteria hash matches.

Open-ended sync can be added later, but it should be modeled explicitly as a
sync mode rather than overloading bounded export behavior.

## SOLID / DRY Rules

- Single Responsibility: export planning, index management, exporting, search,
  verify, render, and Telethon access stay in separate modules.
- Open/Closed: adding another registry command or gateway implementation should
  not require changing exporter internals.
- Liskov Substitution: `exporter.py` depends on the `TelegramGateway` protocol,
  so tests and Telethon can be swapped safely.
- Interface Segregation: search and verify consume local paths; they do not need
  Telegram credentials or gateway methods.
- Dependency Inversion: domain execution depends on gateway abstractions, not
  Telethon directly.
- DRY: identity hashing, path naming, duplicate handling, message selection,
  media refill, manifest writing, and manifest/index normalization each exist in
  one dedicated module.

## Release Gates

Before RC, run:

```bash
uv run pytest
uv run ruff check .
uv run mypy src tests
uv run tg-export exports doctor
uv build
```

`exports doctor` should report zero errors.
Also run the CLI smoke tests in [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md)
before cutting an RC.
