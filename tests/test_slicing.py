from telegram_export_kit.slicing import classify_context, indexes_from_windows, merge_windows


def test_merge_windows_merges_overlaps() -> None:
    windows = merge_windows([3, 5, 12], before=2, after=2, total=20)

    assert windows == [(1, 7), (10, 14)]
    assert indexes_from_windows(windows) == {1, 2, 3, 4, 5, 6, 7, 10, 11, 12, 13, 14}


def test_classify_context_prefers_nearest_target() -> None:
    targets = {3, 10}

    assert classify_context(3, targets) == "target"
    assert classify_context(1, targets) == "before"
    assert classify_context(5, targets) == "after"
    assert classify_context(9, targets) == "before"
    assert classify_context(12, targets) == "after"
