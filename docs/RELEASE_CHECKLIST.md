# Release Checklist

Run this before tagging an RC or handing the tool to someone else.

## Required Gates

```bash
uv run pytest
uv run ruff check .
uv run mypy src tests
uv run tg-export exports doctor
uv build
```

All commands must exit 0. `exports doctor` must report:

```text
OK errors=0 warnings=0
```

## CLI Smoke Tests

```bash
uv run tg-export --help
uv run tg-export export --help
uv run tg-export search --help
uv run tg-export verify --help
uv run tg-export render --help
uv run tg-export render html --help
uv run tg-export render md --help
uv run tg-export exports --help
uv run tg-export exports list
uv run tg-export exports doctor
```

## Data Contract

- `messages.jsonl` is the canonical message data.
- `manifest.json` is the canonical export metadata.
- `exports/.index.json` is a rebuildable cache.
- `manifest.json` must include non-empty `id`, `uuid`, `path_key`, and `criteria_hash`.
- `manifest.json` must include `mode`, `chat.id`, `stats.selected`, and non-empty `runs`.
- `messages_path` must stay `messages.jsonl`.
- `exports doctor` must catch stale index entries and duplicate IDs/UUIDs.

## Manual Regression

Use a small private export and a small group-slice export:

```bash
uv run tg-export export --chat <private_user> --date <YYYY-MM-DD> --new
uv run tg-export search --latest --target-only
uv run tg-export verify --latest
```

```bash
uv run tg-export export \
  --chat <group_username> \
  --sender <target_username> \
  --date <YYYY-MM-DD> \
  --window-before 3 \
  --window-after 3 \
  --new

uv run tg-export search --latest --context target
uv run tg-export search --latest --context before
uv run tg-export verify --latest
```

Expected behavior:

- private export rows use `context_kind=private`
- private export target messages are found with `--target-only`
- group-slice target messages are found with `--context target`
- same criteria without an action is rejected
- `--update` reuses the same export ID
- `--overwrite` reuses the same export ID and rebuilds payload
- `--new` creates a sibling export path

## Documentation

- README examples match the current CLI.
- `docs/ARCHITECTURE.md` matches module boundaries and identity/index rules.
- Obsidian RC checklist is updated after meaningful RC status changes.
