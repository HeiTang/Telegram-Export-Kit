from __future__ import annotations

from collections.abc import Iterable

from telegram_export_kit.models import ContextKind


def merge_windows(
    target_indexes: Iterable[int],
    *,
    before: int,
    after: int,
    total: int,
) -> list[tuple[int, int]]:
    windows = [
        (max(0, index - before), min(total - 1, index + after))
        for index in sorted(set(target_indexes))
    ]
    if not windows:
        return []

    merged: list[tuple[int, int]] = []
    current_start, current_end = windows[0]
    for start, end in windows[1:]:
        if start <= current_end + 1:
            current_end = max(current_end, end)
        else:
            merged.append((current_start, current_end))
            current_start, current_end = start, end
    merged.append((current_start, current_end))
    return merged


def indexes_from_windows(windows: Iterable[tuple[int, int]]) -> set[int]:
    indexes: set[int] = set()
    for start, end in windows:
        indexes.update(range(start, end + 1))
    return indexes


def classify_context(index: int, target_indexes: set[int]) -> ContextKind:
    if index in target_indexes:
        return "target"

    previous_targets = [target for target in target_indexes if target < index]
    next_targets = [target for target in target_indexes if target > index]

    if previous_targets and not next_targets:
        return "after"
    if next_targets and not previous_targets:
        return "before"

    previous_distance = index - max(previous_targets)
    next_distance = min(next_targets) - index
    return "after" if previous_distance <= next_distance else "before"
