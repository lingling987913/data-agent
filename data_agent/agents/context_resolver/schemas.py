"""Pydantic models for context resolution."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class AnaphoraRecord(BaseModel):
    block_id: str
    text_before: str
    text_after: str
    matched_entities: list[str] = Field(default_factory=list)
    resolver_status: Literal["ok", "skipped", "failed"]
