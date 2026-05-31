"""Context for persisting parse-preview figure crops under a run directory."""

from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class FigureStorageContext:
    run_id: str
    base_dir: Path


_figure_storage: ContextVar[Optional[FigureStorageContext]] = ContextVar(
    "parse_figure_storage",
    default=None,
)


def bind_figure_storage(run_id: str, base_dir: Path) -> Token:
    ctx = FigureStorageContext(run_id=run_id.strip(), base_dir=Path(base_dir))
    return _figure_storage.set(ctx)


def reset_figure_storage(token: Token) -> None:
    _figure_storage.reset(token)


def get_figure_storage() -> FigureStorageContext | None:
    return _figure_storage.get()


def figure_output_path(
    file_name: str,
    block_id: str,
    *,
    base_dir: Path | None = None,
) -> Path | None:
    root = Path(base_dir) if base_dir is not None else None
    if root is None:
        ctx = get_figure_storage()
        if ctx is None or not ctx.run_id:
            return None
        root = ctx.base_dir
    stem = Path(file_name).stem or "document"
    safe_stem = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in stem)
    return root / safe_stem / f"{block_id}.jpg"


def resolve_persisted_figure_path(
    run_id: str,
    file_name: str,
    block_id: str,
    *,
    base_dir: Path,
) -> Path | None:
    stem = Path(file_name).stem or "document"
    safe_stem = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in stem)
    path = base_dir / run_id / "figures" / safe_stem / f"{block_id}.jpg"
    return path if path.is_file() else None


__all__ = [
    "FigureStorageContext",
    "bind_figure_storage",
    "reset_figure_storage",
    "figure_output_path",
    "get_figure_storage",
    "resolve_persisted_figure_path",
]
