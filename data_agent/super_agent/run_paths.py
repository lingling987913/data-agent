"""On-disk layout helpers for Super Agent run persistence."""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

RUN_JSON_NAME = "run.json"


def run_dir(runs_dir: Path, run_id: str) -> Path:
    return runs_dir / run_id


def canonical_run_json_path(runs_dir: Path, run_id: str) -> Path:
    return run_dir(runs_dir, run_id) / RUN_JSON_NAME


def legacy_run_json_path(runs_dir: Path, run_id: str) -> Path:
    return runs_dir / f"{run_id}.json"


def resolve_run_json_path(runs_dir: Path, run_id: str) -> Path | None:
    canonical = canonical_run_json_path(runs_dir, run_id)
    if canonical.is_file():
        return canonical
    legacy = legacy_run_json_path(runs_dir, run_id)
    if legacy.is_file():
        return legacy
    return None


def iter_run_json_paths(runs_dir: Path) -> Iterator[tuple[str, Path]]:
    if not runs_dir.is_dir():
        return
    seen: set[str] = set()
    for path in sorted(runs_dir.glob(f"*/{RUN_JSON_NAME}")):
        run_id = path.parent.name
        if run_id not in seen:
            seen.add(run_id)
            yield run_id, path
    for path in sorted(runs_dir.glob("*.json")):
        run_id = path.stem
        if run_id not in seen:
            seen.add(run_id)
            yield run_id, path
