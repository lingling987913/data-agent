"""File-backed TaskBoard snapshot store for SMART committee runs."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from data_agent.core.config import RUNS_DIR, is_task_board_file_store_enabled

logger = logging.getLogger(__name__)

_STORE_VERSION = 1
_DEFAULT_DIR = RUNS_DIR / "task_boards"


def task_board_store_dir() -> Path:
    return _DEFAULT_DIR


def save_task_board(
    run_id: str,
    board_payload: dict[str, Any],
    *,
    summary: dict[str, Any] | None = None,
) -> bool:
    if not is_task_board_file_store_enabled():
        return False
    if not run_id or not isinstance(board_payload, dict):
        return False
    try:
        store_dir = task_board_store_dir()
        store_dir.mkdir(parents=True, exist_ok=True)
        envelope = {
            "version": _STORE_VERSION,
            "run_id": run_id,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "board": board_payload,
            "summary": dict(summary or {}),
        }
        path = store_dir / f"{run_id}.json"
        path.write_text(json.dumps(envelope, ensure_ascii=False, indent=2), encoding="utf-8")
        return True
    except Exception:
        logger.exception("failed to save task board for run %s", run_id)
        return False


def load_task_board(run_id: str) -> dict[str, Any] | None:
    envelope = load_task_board_envelope(run_id)
    if not envelope:
        return None
    board = envelope.get("board")
    return board if isinstance(board, dict) else None


def load_task_board_envelope(run_id: str) -> dict[str, Any] | None:
    if not is_task_board_file_store_enabled() or not run_id:
        return None
    path = task_board_store_dir() / f"{run_id}.json"
    if not path.is_file():
        return None
    try:
        envelope = json.loads(path.read_text(encoding="utf-8"))
        return envelope if isinstance(envelope, dict) else None
    except Exception:
        logger.exception("failed to load task board for run %s", run_id)
        return None


__all__ = [
    "load_task_board",
    "load_task_board_envelope",
    "save_task_board",
    "task_board_store_dir",
]
