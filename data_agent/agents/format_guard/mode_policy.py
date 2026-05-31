"""Processing mode policy for structuring / self-healing pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from data_agent.agents.format_guard.schemas import ProcessingMode

_VALID_MODES: set[str] = {"HIGH_ACCURACY", "HIGH_SPEED", "OPTIMAL"}
_PDF_IMAGE_EXTENSIONS = {
    ".pdf",
    ".png",
    ".jpg",
    ".jpeg",
    ".jp2",
    ".webp",
    ".gif",
    ".bmp",
}


@dataclass(frozen=True)
class ModePolicy:
    parser_type: str
    run_repair_llm: bool
    run_anaphora_llm: bool
    max_repair_blocks: int
    context_window: int


def resolve_mode(processing_mode: str | ProcessingMode) -> ModePolicy:
    """Map processing mode to parser and LLM strategy."""
    mode = (processing_mode or "OPTIMAL").upper()
    if mode not in _VALID_MODES:
        mode = "OPTIMAL"

    from data_agent.core.config import (
        get_structuring_context_blocks,
        get_structuring_max_repair_blocks,
    )

    context_window = get_structuring_context_blocks()
    max_repair = get_structuring_max_repair_blocks()

    if mode == "HIGH_ACCURACY":
        return ModePolicy(
            parser_type="auto",
            run_repair_llm=True,
            run_anaphora_llm=True,
            max_repair_blocks=max_repair,
            context_window=context_window,
        )
    if mode == "HIGH_SPEED":
        return ModePolicy(
            parser_type="local",
            run_repair_llm=False,
            run_anaphora_llm=False,
            max_repair_blocks=0,
            context_window=context_window,
        )
    return ModePolicy(
        parser_type="auto",
        run_repair_llm=True,
        run_anaphora_llm=True,
        max_repair_blocks=max_repair,
        context_window=context_window,
    )


def resolve_parser_type(file_name: str, processing_mode: str | ProcessingMode | None = "OPTIMAL") -> str:
    """Map processing mode and file type to material parser_type."""
    from data_agent.parsing.material_parser_route import resolve_material_parser_route

    mode = (processing_mode or "OPTIMAL").upper()
    if mode not in _VALID_MODES:
        mode = "OPTIMAL"
    ext = Path(file_name).suffix.lower()
    if ext in (".txt", ".md") and mode != "HIGH_ACCURACY":
        return "local"
    if mode == "HIGH_SPEED":
        return resolve_material_parser_route(file_name, "local", mode).parser_type
    if mode == "HIGH_ACCURACY" and ext in _PDF_IMAGE_EXTENSIONS:
        return "mineru_agent"
    return resolve_material_parser_route(file_name, "auto", mode).parser_type
