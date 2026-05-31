"""Four-level structured output adaptation router for Agno agents."""

from __future__ import annotations

import logging
from dataclasses import replace
from enum import Enum
from typing import Any

from data_agent.agno_structured.schemas import (
    DomesticProvider,
    ProviderCapabilityProfile,
    StructuredAdaptationConfig,
    StructuredLevelCode,
)
from data_agent.core.llm_profiles import LLMProfile, get_llm_profile, profile_to_openai_chat
from data_agent.core.models import get_lightweight_model, get_model

logger = logging.getLogger(__name__)


class StructuredLevel(str, Enum):
    A = "A"  # Native JSON Schema strict
    B = "B"  # JSON object + validation/repair
    C = "C"  # parser_model收口
    D = "D"  # strict tool fallback


_LEVEL_ORDER: tuple[StructuredLevelCode, ...] = ("A", "B", "C", "D")

_THINKING_DISABLE: dict[DomesticProvider, dict[str, Any]] = {
    DomesticProvider.QWEN: {"chat_template_kwargs": {"enable_thinking": False}},
    DomesticProvider.GLM: {"thinking": {"type": "disabled"}},
    DomesticProvider.MINIMAX: {},
}


def select_level_from_capabilities(cap: ProviderCapabilityProfile) -> StructuredLevel:
    """Map probe results to the recommended adaptation level."""
    if cap.mock_only:
        logger.warning(
            "structured capability profile for %s is mock-only; using parser/tool fallback instead of verified native mode",
            cap.provider.value,
        )
        return StructuredLevel.C if cap.suitable_as_parser else StructuredLevel.D
    if cap.json_schema_strict and cap.streaming_structured and not cap.thinking_mode_breaks_structured:
        return StructuredLevel.A
    if cap.json_object_mode and cap.streaming_structured:
        return StructuredLevel.B
    if cap.suitable_as_parser:
        return StructuredLevel.C
    return StructuredLevel.D


def _level_index(level: StructuredLevelCode) -> int:
    return _LEVEL_ORDER.index(level)


def resolve_structured_level(
    cap: ProviderCapabilityProfile,
    *,
    prefer: StructuredLevelCode | None = None,
    allow_downgrade: bool = True,
) -> StructuredLevel:
    """Resolve level with optional preference and downgrade safety."""
    recommended = select_level_from_capabilities(cap)
    if prefer is None:
        return recommended

    preferred = StructuredLevel(prefer)
    # Lower index = stronger native support (A best, D fallback).
    if _level_index(preferred.value) >= _level_index(recommended.value) or not allow_downgrade:
        return preferred

    logger.warning(
        "structured_level_downgrade requested=%s recommended=%s — using recommended",
        preferred.value,
        recommended.value,
    )
    return recommended


def build_adaptation_config(
    cap: ProviderCapabilityProfile,
    *,
    level: StructuredLevel | None = None,
    parser_role: str = "light_llm",
) -> StructuredAdaptationConfig:
    """Build resolved adaptation config from capabilities."""
    resolved = level or select_level_from_capabilities(cap)
    provider = cap.provider

    config = StructuredAdaptationConfig(
        level=resolved.value,
        notes=list(cap.notes),
    )

    if resolved == StructuredLevel.A:
        config.supports_native_structured_outputs = True
        config.strict_output = True
        config.use_json_mode = False
    elif resolved == StructuredLevel.B:
        config.use_json_mode = True
        config.supports_native_structured_outputs = False
    elif resolved == StructuredLevel.C:
        config.use_json_mode = True
        config.use_parser_model = True
        config.supports_native_structured_outputs = False
    elif resolved == StructuredLevel.D:
        config.use_strict_tools_fallback = True
        config.use_json_mode = True
        config.supports_native_structured_outputs = False

    if cap.thinking_mode_breaks_structured:
        extra = _THINKING_DISABLE.get(provider)
        if extra:
            config.thinking_disabled_extra_body = extra
            config.notes.append(f"Disable thinking for {provider.value} structured output")

    if config.use_parser_model and not cap.suitable_as_parser:
        config.notes.append("parser_model requested but probe marked parser unsuitable")

    return config


def _merge_extra_body(profile: LLMProfile, extra: dict[str, Any] | None) -> dict[str, Any] | None:
    if not extra:
        return profile.extra_body
    merged = dict(profile.extra_body or {})
    merged.update(extra)
    return merged


def build_model_for_profile(profile: LLMProfile, config: StructuredAdaptationConfig):
    """Create Agno OpenAIChat with structured-output flags."""
    model = profile_to_openai_chat(profile)
    if not config.supports_native_structured_outputs:
        model.supports_native_structured_outputs = False  # type: ignore[attr-defined]
    model.strict_output = config.strict_output  # type: ignore[attr-defined]
    if config.thinking_disabled_extra_body:
        model.extra_body = _merge_extra_body(profile, config.thinking_disabled_extra_body)  # type: ignore[attr-defined]
    return model


def build_agent_kwargs(
    cap: ProviderCapabilityProfile,
    *,
    output_schema: type,
    level: StructuredLevel | None = None,
    main_role: str = "general",
    parser_role: str = "light_llm",
    instructions: list[str] | None = None,
    tools: list[Any] | None = None,
    model_id: str | None = None,
    **extra_agent_kwargs: Any,
) -> dict[str, Any]:
    """Build kwargs dict for ``agno.agent.Agent`` based on adaptation level."""
    config = build_adaptation_config(cap, level=level, parser_role=parser_role)
    main_profile = get_llm_profile(main_role)  # type: ignore[arg-type]
    if model_id:
        main_profile = replace(main_profile, model=model_id)
    main_model = build_model_for_profile(main_profile, config)

    kwargs: dict[str, Any] = {
        "model": main_model,
        "output_schema": output_schema,
        "use_json_mode": config.use_json_mode,
        "markdown": False,
        "instructions": instructions or [],
        **extra_agent_kwargs,
    }

    if config.use_parser_model:
        parser_model = get_lightweight_model()
        if config.thinking_disabled_extra_body:
            parser_model.extra_body = _merge_extra_body(
                get_llm_profile(parser_role),  # type: ignore[arg-type]
                config.thinking_disabled_extra_body,
            )
        kwargs["parser_model"] = parser_model
        kwargs["parser_model_prompt"] = extra_agent_kwargs.get(
            "parser_model_prompt",
            "Extract and format the final answer strictly matching the output schema.",
        )

    if config.use_output_model and not config.use_parser_model:
        kwargs["output_model"] = get_model()
        kwargs.setdefault(
            "output_model_prompt",
            "Format the response to match the output schema exactly.",
        )

    if config.use_strict_tools_fallback:
        kwargs["tools"] = tools or []
        kwargs.setdefault("tool_call_limit", 3)

    logger.info(
        "structured_agent_config level=%s use_json_mode=%s parser=%s tools=%s provider=%s",
        config.level,
        config.use_json_mode,
        config.use_parser_model,
        config.use_strict_tools_fallback,
        cap.provider.value,
    )
    return kwargs


def describe_level(level: StructuredLevel) -> str:
    descriptions = {
        StructuredLevel.A: "Native JSON Schema strict (response_format json_schema strict=True)",
        StructuredLevel.B: "JSON object mode + Pydantic validation/repair",
        StructuredLevel.C: "Main model reasons; parser_model structured收口",
        StructuredLevel.D: "Strict tool calling fallback",
    }
    return descriptions[level]
