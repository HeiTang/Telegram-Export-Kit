# Export Model

This document explains how exported data is identified, stored, and found again.

## Files

Each export contains:

```text
messages.jsonl
assets/
manifest.json
```

`messages.jsonl` is the canonical message store. Rendered HTML and Markdown are
derived artifacts and can be regenerated.

`assets/` stores downloaded images and files.

`manifest.json` stores export identity, source criteria, human-readable labels,
statistics, timestamps, and run history.

## Export ID

Every export has:

- `id`: short stable ID for humans and CLI usage, for example `8f3a2c91`
- `uuid`: full UUID for durable internal identity

Use the short ID with local commands:

```bash
uv run tg-export exports list
uv run tg-export search --export 8f3a2c91 --query "payment"
uv run tg-export render html --export 8f3a2c91
uv run tg-export verify --export 8f3a2c91
```

There is no `--export 1` positional shortcut. Row numbers change when exports
are added, removed, rebuilt, or sorted differently.

## Paths

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
exports/group__c-1001234567890__u777000/2026-07-01/
exports/group__c-1001234567890__all/2026-07-01/
```

Scope key formats:

| Export kind | Scope key |
| --- | --- |
| Private chat | `private__u<user_id>` |
| Group slice | `group__c<chat_id>__u<target_id>` |
| Full group | `group__c<chat_id>__all` |

Paths use resolved Telegram IDs, not usernames, group titles, or display names.
This prevents duplicate directories when a user invokes the same chat by
username one day and numeric ID another day. It also prevents Telegram renames
from changing the export path.

Human-readable names belong in `manifest.json` and `exports list`.

## Message Context

`context_kind` describes why a message is included in an export:

| Export mode | Context values |
| --- | --- |
| Private chat | `private` |
| Group slice | `target`, `before`, `after` |
| Whole group | `target` |

Whole-group exports currently use `target` for every row because there is no
separate selected sender. This keeps the v1 JSONL schema small, but search
filters such as `--sender`, `--query`, `--from`, `--to`, and `--has-media` are
usually more useful than `--context target` for whole-group exports.

## Selector Contract

Local read commands accept the same selector pattern:

```bash
tg-export search [INPUT_PATH] [--latest] [--export ID] [--exports-root PATH]
tg-export verify [INPUT_PATH] [--latest] [--export ID] [--exports-root PATH]
tg-export render html [INPUT_PATH] [--latest] [--export ID] [--exports-root PATH]
tg-export render md [INPUT_PATH] [--latest] [--export ID] [--exports-root PATH]
```

Use exactly one selector:

| Selector | Intent |
| --- | --- |
| `--latest` | Fast exploration after a fresh export. |
| `--export ID` | Stable repeatable command that survives path details. |
| `INPUT_PATH` | Direct file path for scripts, debugging, archives, or non-default roots. |

`--exports-root PATH` changes where `--latest` and `--export ID` look for
exports. It is not itself a selector.

Valid shapes:

```bash
tg-export search --latest
tg-export search --export 8f3a2c91
tg-export search exports/private__u7035465201/2026-07-01
```

## Index And Manifest

`manifest.json` is the source of truth.

`exports/.index.json` is a rebuildable lookup cache used by:

- `exports list`
- `--latest`
- `--export ID`

If the index becomes stale after manual file moves, rebuild it:

```bash
uv run tg-export exports rebuild-index
uv run tg-export exports doctor
```

## Identity Hashes

`path_key` controls the default physical path. It is based on:

- resolved chat ID
- resolved target ID, if any
- date scope

`criteria_hash` controls whether two exports are semantically the same. It
includes:

- mode: `private`, `group_slice`, or `full_chat`
- chat identity
- target identity
- time range
- timezone
- context window for group slices
- output-affecting media policy

Changing `--window-before` or `--window-after` changes the exported message set,
so it changes `criteria_hash`. It does not change the default readable path.
When the path would collide, the CLI asks for an explicit action.

## Existing Export Policy

For the same `criteria_hash`:

| Action | Behavior |
| --- | --- |
| default | Stop and show existing ID/path. |
| `--update` | Reuse ID/path and resume non-destructively. |
| `--overwrite` | Reuse ID/path, verify a staged replacement, then replace payload. |
| `--new` | Create a new ID and sibling path. |

For the same `path_key` but different `criteria_hash`, the default is to stop.
Use `--new` when you intentionally want a sibling export.

The physical destination is checked independently of these hashes. A directory
with payload but no valid matching manifest is rejected rather than resumed.
With `--flat --new`, the new directory is `--out/export__ID`, keeping it inside
the registry root. Different export IDs may intentionally have identical
criteria or share a path key; `exports doctor` accepts these separate exports.

## Counts And Empty Exports

`stats.selected` is the number of messages actually saved in `messages.jsonl`.
Each `runs[].stats.selected` is the selection count for that particular scan.
`--update` retains saved messages that disappeared from Telegram; it does not
sync deletions or edits. Export command output uses `selected` for the scan and
`message_count` for saved rows. An empty `messages.jsonl` is a valid zero-message
export and remains available to list, search, verify, and render.

## Overwrite Recovery

`--overwrite` builds inside a temporary `.overwrite-*` directory on the same
filesystem. It preserves the export ID, UUID, creation time, and run history.
Only a verified replacement is installed; old payload is held in
`.overwrite-backup` during the switch. Ordinary scan, media, and switch errors
leave the original export intact or roll back to it. Rendered HTML and Markdown
are not regenerated automatically; rerun render after a successful overwrite.

Run only one writer per export. This is not a power-loss durability guarantee.
After forced termination, a remaining `.overwrite-backup` blocks further
writes and makes `verify` fail. Index rebuilding ignores `.overwrite-*`
directories so recovery files never become independent exports.

To recover without destroying either version:

1. Stop processes using the export and copy the entire export directory outside
   the exports root, including hidden `.overwrite-*` directories.
2. In the recovery copy, move `.overwrite-backup` and any `.overwrite-*` temporary
   directories outside the copy. Run `tg-export verify RECOVERY_COPY`.
3. If verification succeeds, the current payload is consistent. Otherwise,
   restore each payload entry present in the saved backup (`messages.jsonl`,
   `assets`, `manifest.json`) into the recovery copy, first moving the entry it
   replaces elsewhere. Leave payload entries absent from the backup untouched:
   termination may have happened before they were moved. Verify again.
4. Only use a recovery copy that passes verification. Keep the original and
   backup until recovery is confirmed, then rebuild the registry index for the
   chosen export root. If neither version verifies, preserve both for diagnosis.
