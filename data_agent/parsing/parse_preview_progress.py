"""Optional progress callbacks for long-running parse-preview jobs."""

from __future__ import annotations

from contextvars import ContextVar, Token
from typing import Callable, Optional

ProgressCallback = Callable[[int, str], None]

_progress_callback: ContextVar[Optional[ProgressCallback]] = ContextVar(
    "parse_preview_progress_callback",
    default=None,
)


def bind_progress_callback(callback: ProgressCallback | None) -> Token:
    return _progress_callback.set(callback)


def reset_progress_callback(token: Token) -> None:
    _progress_callback.reset(token)


def report_progress(progress: int, message: str) -> None:
    callback = _progress_callback.get()
    if callback is None:
        return
    callback(max(0, min(100, progress)), message)
