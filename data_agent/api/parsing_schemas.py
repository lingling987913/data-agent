"""Request/response models for standalone parsing API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

ContentType = Literal["path", "base64"]


class ParseDocumentRequest(BaseModel):
    file_name: str
    content_type: ContentType = "base64"
    content: str
    parser_type: str = "auto"
    processing_mode: str = "HIGH_SPEED"
    include_document: bool = True
    skip_enhancement: bool = True
    include_artifact: bool = True


class ParseDocumentResponse(BaseModel):
    file_name: str = ""
    file_type: str = ""
    parse_status: str = "failed"
    parser_name: str = ""
    content: str = ""
    warnings: list[str] = Field(default_factory=list)
    document: dict[str, Any] | None = None
    parse_artifact: dict[str, Any] = Field(default_factory=dict)
    parser_trace_summary: dict[str, Any] = Field(default_factory=dict)
    parser_traces: list[dict[str, Any]] = Field(default_factory=list)
    parser_fallback_logs: list[dict[str, Any]] = Field(default_factory=list)
    self_healing_records: list[dict[str, Any]] = Field(default_factory=list)
    enhancement_skipped: bool = True
