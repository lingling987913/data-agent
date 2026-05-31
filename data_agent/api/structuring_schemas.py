"""Request/response models for structuring REST API."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from data_agent.parsing.schemas import DocumentSectionTree, ParsedDocument, ParsedDocumentBlock
from data_agent.agents.format_guard.schemas import ProcessingMode, StructuredCorpusResult

ContentType = Literal["path", "base64"]


class StructuringHealRequest(BaseModel):
    file_name: str
    content_type: ContentType = "base64"
    content: str
    processing_mode: ProcessingMode = "OPTIMAL"
    parser_type: str | None = None
    build_section_tree: bool = True


class StructuringHealResponse(BaseModel):
    document: ParsedDocument
    markdown: str
    section_tree: DocumentSectionTree | None = None
    result: StructuredCorpusResult


class HealBlocksRequest(BaseModel):
    document_id: str = ""
    file_name: str = "inline.md"
    blocks: list[ParsedDocumentBlock]
    processing_mode: ProcessingMode = "OPTIMAL"


class ModeInfo(BaseModel):
    mode: str
    parser_type: str
    run_repair_llm: bool
    run_anaphora_llm: bool
    description: str = ""


class StructuringModesResponse(BaseModel):
    default_mode: str
    modes: list[ModeInfo] = Field(default_factory=list)
