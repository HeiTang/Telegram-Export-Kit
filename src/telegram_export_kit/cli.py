from __future__ import annotations

import asyncio
import sys
from collections import Counter
from collections.abc import Mapping
from contextlib import nullcontext
from datetime import datetime, tzinfo
from pathlib import Path
from typing import Annotated, Any, cast

import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskID,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table
from telethon import errors

from telegram_export_kit.config import AppConfig, ConfigError
from telegram_export_kit.export_index import (
    ExportEntry,
    ExportIndexDoctorResult,
    discover_exports,
    doctor_export_index,
    rebuild_export_index,
    resolve_export_messages_path,
    upsert_export_record,
)
from telegram_export_kit.export_plan import (
    ExistingExportError,
    ExportPlanError,
    PathCollisionError,
    plan_export,
    staged_overwrite,
)
from telegram_export_kit.exporter import export_chat
from telegram_export_kit.jsonl import dumps_line
from telegram_export_kit.models import ExportOptions
from telegram_export_kit.renderer import RenderFormat, render
from telegram_export_kit.search import (
    SearchContext,
    SearchResult,
    search_messages,
)
from telegram_export_kit.telethon_gateway import TelethonGateway
from telegram_export_kit.utils import parse_datetime, resolve_timezone
from telegram_export_kit.verify import VerifyResult, verify_export

app = typer.Typer(no_args_is_help=True)
auth_app = typer.Typer(no_args_is_help=True)
dialogs_app = typer.Typer(no_args_is_help=True)
members_app = typer.Typer(no_args_is_help=True)
senders_app = typer.Typer(no_args_is_help=True)
render_app = typer.Typer(no_args_is_help=True)
exports_app = typer.Typer(no_args_is_help=True)
console = Console()

app.add_typer(auth_app, name="auth")
app.add_typer(dialogs_app, name="dialogs")
app.add_typer(members_app, name="members")
app.add_typer(senders_app, name="senders")
app.add_typer(render_app, name="render")
app.add_typer(exports_app, name="exports")


EnvFileOption = Annotated[Path, typer.Option("--env-file", help="Path to .env file.")]
TimezoneOption = Annotated[
    str | None,
    typer.Option(
        "--timezone",
        help="Display/date timezone, e.g. Asia/Taipei. Defaults to TG_TIMEZONE or local timezone.",
    ),
]
SearchFormat = Annotated[
    str,
    typer.Option("--format", help="Output format: table, jsonl, or md."),
]


def _config(env_file: Path) -> AppConfig:
    try:
        return AppConfig.from_env(env_file=env_file)
    except ConfigError as exc:
        raise typer.BadParameter(str(exc)) from exc


def _progress_int(payload: Mapping[str, object], key: str) -> int:
    value = payload[key]
    if not isinstance(value, int):
        raise TypeError(f"Progress payload {key} must be int")
    return value


def _timezone_label(requested: str | None, timezone: tzinfo) -> str:
    return requested or getattr(timezone, "key", None) or timezone.tzname(None) or str(timezone)


def _resolve_timezone_or_raise(value: str | None) -> tzinfo:
    try:
        return resolve_timezone(value)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc


def _available_message_files(root: Path = Path("exports")) -> list[Path]:
    if not root.exists():
        return []
    return sorted(root.glob("**/messages.jsonl"))


def _render_or_exit(
    input_path: Path,
    *,
    output: Path | None,
    fmt: RenderFormat,
    timezone: str | None,
) -> Path:
    if not input_path.exists():
        console.print(f"[red]messages.jsonl not found:[/red] {input_path}")
        candidates = _available_message_files()
        if candidates:
            console.print("\nAvailable message files:")
            for candidate in candidates[:20]:
                console.print(f"- {candidate}")
            if len(candidates) > 20:
                console.print(f"... and {len(candidates) - 20} more")
        else:
            console.print("\nNo messages.jsonl found under exports/. Run export first.")
        raise typer.Exit(1)

    try:
        return render(input_path, output_path=output, fmt=fmt, timezone=timezone)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc


def _print_search_results(results: list[SearchResult], *, fmt: str) -> None:
    if fmt == "jsonl":
        for result in results:
            sys.stdout.buffer.write(dumps_line(result.record))
        return

    if fmt == "md":
        for result in results:
            console.print(f"- #{result.id} {result.date} {result.sender}: {result.snippet}")
        return

    if fmt != "table":
        raise typer.BadParameter("--format must be one of: table, jsonl, md")

    table = Table("id", "date", "sender", "context", "media", "snippet", "anchor")
    for result in results:
        table.add_row(
            str(result.id),
            result.date,
            result.sender,
            result.context_kind,
            str(result.media_count),
            result.snippet,
            result.anchor,
        )
    console.print(table)


def _print_verify_result(result: VerifyResult) -> None:
    color = "green" if result.ok else "red"
    console.print(
        f"[{color}]{'OK' if result.ok else 'FAILED'}[/] "
        f"messages={result.message_count} assets={result.asset_count} "
        f"errors={result.error_count} warnings={result.warning_count}"
    )
    for issue in result.issues:
        label = "ERROR" if issue.severity == "error" else "WARN"
        line = f":{issue.line}" if issue.line is not None else ""
        style = "red" if issue.severity == "error" else "yellow"
        console.print(f"[{style}]{label}[/] {issue.code}{line}: {issue.message}")


def _print_exports(entries: list[ExportEntry]) -> None:
    table = Table("ID", "updated", "chat", "target", "mode", "scope", "messages", "path")
    for entry in entries:
        table.add_row(
            entry.id,
            entry.updated_at,
            entry.chat,
            entry.target,
            entry.mode,
            entry.date_scope,
            str(entry.message_count),
            str(entry.root_dir),
        )
    console.print(table)


def _print_existing_export(entry: ExportEntry) -> None:
    console.print(f"Existing export: id={entry.id} path={entry.root_dir}")


def _print_conflicting_exports(entries: list[ExportEntry]) -> None:
    console.print("Conflicting exports with the same physical scope:")
    for entry in entries:
        console.print(
            f"- id={entry.id} path={entry.root_dir} "
            f"criteria_hash={entry.criteria_hash}"
        )


def _print_index_doctor(root: Path) -> ExportIndexDoctorResult:
    result = doctor_export_index(root)
    color = "green" if result.ok else "red"
    console.print(
        f"[{color}]{'OK' if result.ok else 'FAILED'}[/] "
        f"errors={result.error_count} warnings={result.warning_count}"
    )
    for issue in result.issues:
        label = "ERROR" if issue.severity == "error" else "WARN"
        style = "red" if issue.severity == "error" else "yellow"
        path = f" {issue.path}" if issue.path is not None else ""
        console.print(f"[{style}]{label}[/] {issue.code}:{path} {issue.message}")
    return result


def _resolve_time_range(
    *,
    date: str | None,
    start_date: str | None,
    end_date: str | None,
    timezone: tzinfo,
) -> tuple[datetime | None, datetime | None, str]:
    simple_range = start_date is not None or end_date is not None
    selected_modes = sum([date is not None, simple_range])
    if selected_modes > 1:
        raise typer.BadParameter("Use only one date mode: --date or --start-date/--end-date.")

    if date is not None:
        return (
            parse_datetime(date, timezone=timezone),
            parse_datetime(date, next_day=True, timezone=timezone),
            date,
        )

    if simple_range:
        if start_date is None or end_date is None:
            raise typer.BadParameter("--start-date and --end-date must be used together.")
        return (
            parse_datetime(start_date, timezone=timezone),
            parse_datetime(end_date, next_day=True, timezone=timezone),
            f"{start_date}_to_{end_date}",
        )

    return None, None, "all"


def _resolve_selected_messages_path(
    path: Path | None,
    *,
    latest: bool,
    export_id: str | None,
    exports_root: Path,
) -> Path:
    try:
        messages_path = resolve_export_messages_path(
            path,
            root=exports_root,
            latest=latest,
            export_id=export_id,
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    if not messages_path.exists():
        console.print(f"[red]messages.jsonl not found:[/red] {messages_path}")
        raise typer.Exit(1)
    return messages_path


def _resolve_render_messages_path(
    path: Path | None,
    *,
    latest: bool,
    export_id: str | None,
    exports_root: Path,
) -> Path:
    selected_modes = sum([path is not None, latest, export_id is not None])
    if selected_modes != 1:
        raise typer.BadParameter("Provide exactly one of: INPUT_PATH, --latest, or --export.")
    if path is not None:
        return path / "messages.jsonl" if path.is_dir() else path
    return _resolve_selected_messages_path(
        None,
        latest=latest,
        export_id=export_id,
        exports_root=exports_root,
    )


@exports_app.command("list")
def exports_list(
    root: Annotated[Path, typer.Option("--root", help="Export root directory.")] = Path("exports"),
) -> None:
    entries = discover_exports(root)
    if not entries:
        console.print(f"No exports found under {root}.")
        return
    _print_exports(entries)


@exports_app.command("rebuild-index")
def exports_rebuild_index(
    root: Annotated[Path, typer.Option("--root", help="Export root directory.")] = Path("exports"),
) -> None:
    entries = rebuild_export_index(root)
    console.print(f"Rebuilt {root / '.index.json'} with {len(entries)} exports.")


@exports_app.command("doctor")
def exports_doctor(
    root: Annotated[Path, typer.Option("--root", help="Export root directory.")] = Path("exports"),
) -> None:
    result = _print_index_doctor(root)
    if not result.ok:
        raise typer.Exit(1)


@app.command("search")
def search_command(
    input_path: Annotated[
        Path | None,
        typer.Argument(help="Export directory or messages.jsonl path."),
    ] = None,
    query: Annotated[str | None, typer.Option("--query", help="Text query.")] = None,
    sender: Annotated[
        str | None,
        typer.Option("--sender", help="Sender id, username, or display name."),
    ] = None,
    date_from: Annotated[
        str | None,
        typer.Option("--from", help="Start local date, e.g. 2026-01-01."),
    ] = None,
    date_to: Annotated[
        str | None,
        typer.Option("--to", help="End local date, e.g. 2026-01-31."),
    ] = None,
    context: Annotated[
        SearchContext | None,
        typer.Option("--context", help="private, target, before, or after."),
    ] = None,
    target_only: Annotated[
        bool,
        typer.Option("--target-only", help="Only messages sent by the export target."),
    ] = False,
    has_media: Annotated[bool, typer.Option("--has-media", help="Only rows with media.")] = False,
    limit: Annotated[int | None, typer.Option("--limit", min=1)] = None,
    latest: Annotated[bool, typer.Option("--latest", help="Use the newest export.")] = False,
    export_id: Annotated[
        str | None,
        typer.Option("--export", help="Use a stable export ID from `exports list`."),
    ] = None,
    exports_root: Annotated[
        Path,
        typer.Option("--exports-root", help="Root used by --latest and --export."),
    ] = Path("exports"),
    fmt: SearchFormat = "table",
    timezone: TimezoneOption = None,
) -> None:
    messages_path = _resolve_selected_messages_path(
        input_path,
        latest=latest,
        export_id=export_id,
        exports_root=exports_root,
    )
    try:
        results = search_messages(
            messages_path,
            query=query,
            sender=sender,
            date_from=date_from,
            date_to=date_to,
            context=context,
            target_only=target_only,
            has_media=has_media,
            limit=limit,
            timezone=timezone,
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    _print_search_results(results, fmt=fmt)


@app.command("verify")
def verify_command(
    path: Annotated[
        Path | None,
        typer.Argument(help="Export directory or messages.jsonl path."),
    ] = None,
    latest: Annotated[bool, typer.Option("--latest", help="Use the newest export.")] = False,
    export_id: Annotated[
        str | None,
        typer.Option("--export", help="Use a stable export ID from `exports list`."),
    ] = None,
    exports_root: Annotated[
        Path,
        typer.Option("--exports-root", help="Root used by --latest and --export."),
    ] = Path("exports"),
) -> None:
    messages_path = _resolve_selected_messages_path(
        path,
        latest=latest,
        export_id=export_id,
        exports_root=exports_root,
    )
    result = verify_export(messages_path)
    _print_verify_result(result)
    if not result.ok:
        raise typer.Exit(1)


@auth_app.command("login")
def auth_login(env_file: EnvFileOption = Path(".env")) -> None:
    async def run() -> None:
        cfg = _config(env_file)
        gateway = TelethonGateway.from_config(cfg)
        async with gateway:
            await gateway.login(phone=cfg.phone)
            me = await gateway.client.get_me()
            console.print(f"Logged in as {gateway.sender_record(me).display_name}")

    asyncio.run(run())


@dialogs_app.command("list")
def dialogs_list(
    env_file: EnvFileOption = Path(".env"),
    limit: int = typer.Option(100, min=1),
) -> None:
    async def run() -> None:
        cfg = _config(env_file)
        gateway = TelethonGateway.from_config(cfg)
        async with gateway:
            await gateway.ensure_authorized(phone=cfg.phone)
            table = Table("id", "type", "title", "username")
            async for dialog in gateway.client.iter_dialogs(limit=limit):
                record = gateway.chat_record(dialog.entity)
                table.add_row(
                    str(record.id),
                    record.type,
                    record.title or "",
                    record.username or "",
                )
            console.print(table)

    asyncio.run(run())


@app.command("export")
def export_command(
    chat: Annotated[str, typer.Option("--chat", help="Chat id, username, or phone.")],
    out: Annotated[Path, typer.Option("--out", help="Output directory.")] = Path("exports"),
    sender: Annotated[
        str | None,
        typer.Option("--sender", help="Optional sender id, username, or phone filter."),
    ] = None,
    date: Annotated[
        str | None,
        typer.Option("--date", help="Single local date, e.g. 2026-01-31."),
    ] = None,
    start_date: Annotated[
        str | None,
        typer.Option("--start-date", help="Range start date, e.g. 2026-01-01."),
    ] = None,
    end_date: Annotated[
        str | None,
        typer.Option("--end-date", help="Range end date, e.g. 2026-01-31."),
    ] = None,
    window_before: Annotated[int, typer.Option("--window-before", min=0)] = 20,
    window_after: Annotated[int, typer.Option("--window-after", min=0)] = 20,
    no_media: Annotated[bool, typer.Option("--no-media", help="Do not download media.")] = False,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Count only; write nothing.")] = False,
    no_resume: Annotated[bool, typer.Option("--no-resume", help="Ignore existing JSONL.")] = False,
    update: Annotated[
        bool,
        typer.Option("--update", help="Update an existing export with the same criteria."),
    ] = False,
    overwrite: Annotated[
        bool,
        typer.Option("--overwrite", help="Destructively rebuild an existing export."),
    ] = False,
    new: Annotated[
        bool,
        typer.Option("--new", help="Force a new export ID and sibling directory."),
    ] = False,
    flat: Annotated[
        bool,
        typer.Option("--flat", help="Write messages.jsonl directly into --out."),
    ] = False,
    timezone: TimezoneOption = None,
    env_file: EnvFileOption = Path(".env"),
) -> None:
    async def run() -> None:
        cfg = _config(env_file)
        timezone_name = timezone or cfg.timezone
        display_timezone = _resolve_timezone_or_raise(timezone_name)
        since_dt, until_dt, date_label = _resolve_time_range(
            date=date,
            start_date=start_date,
            end_date=end_date,
            timezone=display_timezone,
        )
        selected_actions = sum([update, overwrite, new])
        if selected_actions > 1:
            raise typer.BadParameter("Use only one of: --update, --overwrite, or --new.")
        if no_resume and not overwrite:
            raise typer.BadParameter("--no-resume can duplicate rows; use --overwrite instead.")

        gateway = TelethonGateway.from_config(cfg)
        async with gateway:
            await gateway.ensure_authorized(phone=cfg.phone)
            chat_entity = await gateway.resolve_chat(chat)
            chat_record = gateway.chat_record(chat_entity)
            is_private = gateway.is_private_chat(chat_entity)
            if sender is not None:
                sender_entity = await gateway.resolve_user(sender)
                target_record = gateway.sender_record(sender_entity)
            elif is_private:
                target_record = gateway.sender_record(chat_entity)
            else:
                target_record = None

            timezone_label = _timezone_label(timezone_name, display_timezone)
            try:
                plan = plan_export(
                    out=out,
                    chat_ref=chat,
                    sender_ref=sender,
                    chat_record=chat_record,
                    target_record=target_record,
                    date_label=date_label,
                    date=date,
                    start_date=start_date,
                    end_date=end_date,
                    since=since_dt,
                    until=until_dt,
                    timezone=timezone_label,
                    window_before=window_before,
                    window_after=window_after,
                    flat=flat,
                    update=update,
                    overwrite=overwrite,
                    new=new,
                    dry_run=dry_run,
                    resume=not no_resume,
                )
            except ExistingExportError as exc:
                console.print(f"[red]{exc}[/red]")
                _print_existing_export(exc.entry)
                console.print(
                    "Use --update to resume, --overwrite to rebuild, "
                    "or --new for a sibling export."
                )
                raise typer.Exit(1) from exc
            except PathCollisionError as exc:
                console.print(f"[red]{exc}[/red]")
                _print_conflicting_exports(exc.entries)
                console.print("Use --new to keep the existing export and create a sibling path.")
                raise typer.Exit(1) from exc
            except ExportPlanError as exc:
                console.print(f"[red]{exc}[/red]")
                raise typer.Exit(1) from exc

            transaction = (
                staged_overwrite(plan.out_dir) if plan.should_reset else nullcontext(plan.out_dir)
            )
            try:
                with transaction as write_dir:
                    options = ExportOptions(
                        chat=chat,
                        sender=sender,
                        out_dir=write_dir,
                        since=since_dt,
                        until=until_dt,
                        timezone=timezone_label,
                        window_before=window_before,
                        window_after=window_after,
                        download_media=not no_media,
                        dry_run=dry_run,
                        resume=plan.resume,
                        export_id=plan.export_id,
                        export_uuid=plan.export_uuid,
                        source=plan.source,
                        path_key=plan.path_key,
                        criteria_hash=plan.criteria_hash,
                    )
                    with Progress(
                        SpinnerColumn(),
                        TextColumn("[progress.description]{task.description}"),
                        BarColumn(),
                        TaskProgressColumn(),
                        TimeElapsedColumn(),
                        console=console,
                    ) as progress:
                        scan_task = progress.add_task("Scanning messages", total=None)
                        write_task: TaskID | None = None

                        def on_progress(event: str, payload: Mapping[str, object]) -> None:
                            nonlocal write_task

                            if event == "scan":
                                progress.update(
                                    scan_task,
                                    description=f"Scanning messages ({payload['seen']})",
                                )
                                return

                            if event == "selected":
                                seen = _progress_int(payload, "seen")
                                selected = _progress_int(payload, "selected")
                                target_messages = _progress_int(payload, "target_messages")
                                progress.update(
                                    scan_task,
                                    total=seen,
                                    completed=seen,
                                    description=(
                                        f"Scanned {seen}; selected {selected}; "
                                        f"target {target_messages}"
                                    ),
                                )
                                write_task = progress.add_task("Writing export", total=selected)
                                return

                            if write_task is None:
                                return

                            if event in {"skip_existing", "dry_run_selected", "write_start"}:
                                message_id = payload["message_id"]
                                position = payload["position"]
                                total = payload["total"]
                                progress.update(
                                    write_task,
                                    description=f"Message #{message_id} ({position}/{total})",
                                )

                            if event in {"skip_existing", "dry_run_selected", "written"}:
                                progress.advance(write_task)

                        result = await export_chat(gateway, options, progress=on_progress)
            except (ExportPlanError, ValueError, OSError) as exc:
                console.print(f"[red]{exc}[/red]")
                raise typer.Exit(1) from exc
            except errors.FloodWaitError as exc:
                console.print(f"Telegram flood wait: retry after {exc.seconds}s")
                raise typer.Exit(1) from exc

        if not result.dry_run:
            upsert_export_record(
                out,
                export_id=plan.export_id,
                export_uuid=plan.export_uuid,
                path=plan.out_dir,
                path_key=plan.path_key,
                criteria_hash=plan.criteria_hash,
                chat=plan.chat_label,
                target=plan.target_label,
                mode=plan.mode,
                scope=plan.scope,
                message_count=result.message_count,
            )

        console.print(
            {
                "id": plan.export_id,
                "out_dir": str(plan.out_dir),
                "total_seen": result.total_seen,
                "target_messages": result.target_messages,
                "selected": result.selected,
                "message_count": result.message_count,
                "written": result.written,
                "media_updated": result.media_updated,
                "skipped_existing": result.skipped_existing,
                "dry_run": result.dry_run,
            }
        )

    asyncio.run(run())


@members_app.command("list")
def members_list(
    chat: Annotated[str, typer.Option("--chat", help="Group id or username.")],
    limit: Annotated[int | None, typer.Option("--limit", min=1)] = None,
    search: Annotated[str | None, typer.Option("--search", help="Search members by name.")] = None,
    env_file: EnvFileOption = Path(".env"),
) -> None:
    async def run() -> None:
        cfg = _config(env_file)
        gateway = TelethonGateway.from_config(cfg)
        async with gateway:
            await gateway.ensure_authorized(phone=cfg.phone)
            chat_entity = await gateway.resolve_chat(chat)
            table = Table("id", "username", "display_name", "bot")
            async for member in gateway.client.iter_participants(
                chat_entity,
                limit=limit,
                search=search or "",
            ):
                record = gateway.sender_record(member)
                table.add_row(
                    str(record.id or ""),
                    record.username or "",
                    record.display_name or "",
                    str(bool(record.is_bot)).lower(),
                )
            console.print(table)

    asyncio.run(run())


@senders_app.command("list")
def senders_list(
    chat: Annotated[str, typer.Option("--chat", help="Chat id or username.")],
    limit: Annotated[int, typer.Option("--limit", min=1)] = 5000,
    env_file: EnvFileOption = Path(".env"),
) -> None:
    async def run() -> None:
        cfg = _config(env_file)
        gateway = TelethonGateway.from_config(cfg)
        async with gateway:
            await gateway.ensure_authorized(phone=cfg.phone)
            chat_entity = await gateway.resolve_chat(chat)
            counts: Counter[int] = Counter()
            records: dict[int, object] = {}
            async for message in gateway.client.iter_messages(chat_entity, limit=limit):
                sender_id = getattr(message, "sender_id", None)
                if sender_id is None:
                    continue
                sender_id = int(sender_id)
                counts[sender_id] += 1
                if sender_id not in records:
                    sender = await cast(Any, message).get_sender()
                    if sender is not None:
                        records[sender_id] = sender

            table = Table("id", "username", "display_name", "messages")
            for sender_id, count in counts.most_common():
                record = gateway.sender_record(records.get(sender_id, object()))
                table.add_row(
                    str(sender_id),
                    record.username or "",
                    record.display_name or "",
                    str(count),
                )
            console.print(table)

    asyncio.run(run())


@render_app.command("html")
def render_html(
    input_path: Annotated[
        Path | None,
        typer.Argument(help="Export directory or messages.jsonl path."),
    ] = None,
    output: Annotated[Path | None, typer.Option("--out", help="Output HTML path.")] = None,
    latest: Annotated[bool, typer.Option("--latest", help="Use the newest export.")] = False,
    export_id: Annotated[
        str | None,
        typer.Option("--export", help="Use a stable export ID from `exports list`."),
    ] = None,
    exports_root: Annotated[
        Path,
        typer.Option("--exports-root", help="Root used by --latest and --export."),
    ] = Path("exports"),
    timezone: TimezoneOption = None,
    env_file: EnvFileOption = Path(".env"),
) -> None:
    if env_file.exists():
        load_dotenv(env_file)
    messages_path = _resolve_render_messages_path(
        input_path,
        latest=latest,
        export_id=export_id,
        exports_root=exports_root,
    )
    rendered = _render_or_exit(messages_path, output=output, fmt="html", timezone=timezone)
    console.print(str(rendered))


@render_app.command("md")
def render_md(
    input_path: Annotated[
        Path | None,
        typer.Argument(help="Export directory or messages.jsonl path."),
    ] = None,
    output: Annotated[Path | None, typer.Option("--out", help="Output Markdown path.")] = None,
    latest: Annotated[bool, typer.Option("--latest", help="Use the newest export.")] = False,
    export_id: Annotated[
        str | None,
        typer.Option("--export", help="Use a stable export ID from `exports list`."),
    ] = None,
    exports_root: Annotated[
        Path,
        typer.Option("--exports-root", help="Root used by --latest and --export."),
    ] = Path("exports"),
    timezone: TimezoneOption = None,
    env_file: EnvFileOption = Path(".env"),
) -> None:
    if env_file.exists():
        load_dotenv(env_file)
    messages_path = _resolve_render_messages_path(
        input_path,
        latest=latest,
        export_id=export_id,
        exports_root=exports_root,
    )
    rendered = _render_or_exit(messages_path, output=output, fmt="md", timezone=timezone)
    console.print(str(rendered))


if __name__ == "__main__":
    app()
