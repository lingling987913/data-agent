"""Remove on-disk artifacts associated with a review task."""

from __future__ import annotations

import shutil
from pathlib import Path


def remove_path(path: Path) -> list[str]:
    if not path.exists():
        return []
    target = str(path)
    if path.is_file() or path.is_symlink():
        path.unlink(missing_ok=True)
    else:
        shutil.rmtree(path, ignore_errors=True)
    return [target]


def remove_task_artifacts(review_id: str, *paths: Path) -> list[str]:
    removed: list[str] = []
    for path in paths:
        removed.extend(remove_path(path))
    return removed
