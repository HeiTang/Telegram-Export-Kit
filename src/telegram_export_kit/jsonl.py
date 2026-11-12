from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

try:
    import orjson
except ImportError:  # pragma: no cover
    orjson = None  # type: ignore[assignment]

from pydantic import BaseModel


def _to_jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json", exclude_none=True)
    return value


def dumps_line(value: Any) -> bytes:
    payload = _to_jsonable(value)
    if orjson is not None:
        return orjson.dumps(payload, option=orjson.OPT_APPEND_NEWLINE)
    return (json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n").encode()


def append_jsonl(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("ab") as fh:
        fh.write(dumps_line(value))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("wb") as fh:
        fh.write(dumps_line(value).rstrip(b"\n"))
    tmp_path.replace(path)


def write_jsonl(path: Path, values: Iterable[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("wb") as fh:
        for value in values:
            fh.write(dumps_line(value))
    tmp_path.replace(path)


def read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("rb") as fh:
        for line in fh:
            if not line.strip():
                continue
            if orjson is not None:
                yield orjson.loads(line)
            else:
                yield json.loads(line)
