"""Internal schemas for parse rationality calibration."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from data_agent.parsing.schemas import ParsedDocumentBlock, ParseCalibrationRecord

CalibrationIssueType = Literal[
    "numeric_outlier",
    "symbol_confusion",
    "unit_mismatch",
    "context_conflict",
    "other",
]


@dataclass
class CalibrationContext:
    block: ParsedDocumentBlock
    before_blocks: list[ParsedDocumentBlock] = field(default_factory=list)
    after_blocks: list[ParsedDocumentBlock] = field(default_factory=list)
    issue_type: CalibrationIssueType = "other"
    reason: str = ""
    evidence: list[str] = field(default_factory=list)
    heuristic_record: ParseCalibrationRecord | None = None


def block_context_text(ctx: CalibrationContext) -> str:
    parts: list[str] = []
    for label, blocks in (
        ("前文", ctx.before_blocks),
        ("当前", [ctx.block]),
        ("后文", ctx.after_blocks),
    ):
        snippets = [b.text.strip() for b in blocks if b.text and b.text.strip()]
        if snippets:
            parts.append(f"{label}: " + "\n".join(snippets))
    return "\n".join(parts)
