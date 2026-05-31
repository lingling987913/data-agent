"""Pydantic schemas for Agno structured output adaptation."""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class DomesticProvider(str, Enum):
    QWEN = "qwen"
    GLM = "glm"
    MINIMAX = "minimax"
    OPENAI = "openai"
    UNKNOWN = "unknown"


StructuredLevelCode = Literal["A", "B", "C", "D"]


class ProviderCapabilityProfile(BaseModel):
    """Result of a provider capability probe."""

    provider: DomesticProvider
    model: str = ""
    base_url: str = ""
    openai_compatible: bool = False
    json_schema_strict: bool = False
    json_object_mode: bool = False
    function_calling: bool = False
    strict_tools: bool = False
    streaming_structured: bool = False
    thinking_mode_breaks_structured: bool = True
    suitable_as_main: bool = False
    suitable_as_parser: bool = False
    recommended_level: StructuredLevelCode = "D"
    probe_mode: Literal["mock", "live"] = "mock"
    verified: bool = False
    mock_only: bool = False
    probe_errors: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class CapabilityMatrixRow(BaseModel):
    """Human-readable row for capability comparison tables."""

    provider: DomesticProvider
    level_a: bool = False
    level_b: bool = False
    level_c: bool = False
    level_d: bool = True
    main_model_notes: str = ""
    parser_model_notes: str = ""
    thinking_warning: str = ""


class StructuredAdaptationConfig(BaseModel):
    """Resolved adaptation config for building Agno Agent/Team instances."""

    level: StructuredLevelCode
    use_json_mode: bool = False
    use_parser_model: bool = False
    use_output_model: bool = False
    use_strict_tools_fallback: bool = False
    supports_native_structured_outputs: bool = False
    strict_output: bool = True
    thinking_disabled_extra_body: dict[str, Any] | None = None
    notes: list[str] = Field(default_factory=list)


# --- Example output schemas used by demos and smoke tests ---


class EntityExtractionOutput(BaseModel):
    """Minimal structured output for capability smoke tests."""

    entity: str = Field(..., description="Primary entity name")
    category: str = Field(..., description="Entity category")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence score")


class TeamSummaryOutput(BaseModel):
    """Example team-level structured output."""

    headline: str = Field(..., description="One-line summary")
    key_points: list[str] = Field(..., min_length=1, max_length=5)
    risk_level: Literal["low", "medium", "high"] = "medium"


class StrictToolPayload(BaseModel):
    """Payload returned via strict tool calling fallback."""

    answer: str
    sources: list[str] = Field(default_factory=list)
