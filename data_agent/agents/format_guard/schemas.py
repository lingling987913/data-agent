"""Pydantic models for the structuring / self-healing pipeline."""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

from data_agent.parsing.schemas import DocumentSectionTree, ParsedDocument

from data_agent.agents.context_resolver.schemas import AnaphoraRecord

ProcessingMode = Literal["HIGH_ACCURACY", "HIGH_SPEED", "OPTIMAL"]


class FormatDamageType(str, Enum):
    UNCLOSED_HTML_TABLE = "unclosed_html_table"
    UNCLOSED_HTML_TR = "unclosed_html_tr"
    UNCLOSED_HTML_TD = "unclosed_html_td"
    ODD_INLINE_LATEX = "odd_inline_latex"
    ODD_BLOCK_LATEX = "odd_block_latex"


class BlockDamageReport(BaseModel):
    block_id: str
    order_index: int
    damage_types: list[FormatDamageType]
    snippet: str = ""
    detector_version: str = "1.0"


class RepairRecord(BaseModel):
    block_id: str
    damage_types: list[FormatDamageType]
    text_before: str
    text_after: str
    repair_status: Literal["ok", "skipped", "failed"]
    model_id: str = ""
    latency_ms: int = 0
    token_estimate: int = 0


class HealingStats(BaseModel):
    blocks_total: int
    damaged_count: int
    repaired_count: int
    anaphora_resolved_count: int
    warnings: list[str] = Field(default_factory=list)


class StructuredCorpusResult(BaseModel):
    document: ParsedDocument
    section_tree: DocumentSectionTree | None = None
    damage_reports: list[BlockDamageReport] = Field(default_factory=list)
    repair_records: list[RepairRecord] = Field(default_factory=list)
    anaphora_records: list[AnaphoraRecord] = Field(default_factory=list)
    stats: HealingStats
    processing_mode: ProcessingMode
