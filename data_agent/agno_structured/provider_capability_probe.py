"""Provider capability probes for Qwen, GLM, MiniMax and OpenAI-compatible endpoints."""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from data_agent.agno_structured.schemas import DomesticProvider, ProviderCapabilityProfile
from data_agent.core.llm_profiles import LLMProfile, get_llm_profile

logger = logging.getLogger(__name__)

LIVE_PROBE_ENV = "AGNO_STRUCTURED_LIVE_PROBE"

_PROVIDER_HINTS: dict[DomesticProvider, tuple[str, ...]] = {
    DomesticProvider.QWEN: ("qwen", "dashscope", "siliconflow", "modelscope"),
    DomesticProvider.GLM: ("glm", "bigmodel.cn", "zhipu"),
    DomesticProvider.MINIMAX: ("minimax", "minimaxi"),
}

# Conservative defaults when live probe is unavailable.
_MOCK_DEFAULTS: dict[DomesticProvider, dict[str, Any]] = {
    DomesticProvider.QWEN: {
        "openai_compatible": True,
        "json_schema_strict": False,
        "json_object_mode": True,
        "function_calling": True,
        "strict_tools": False,
        "streaming_structured": True,
        "thinking_mode_breaks_structured": True,
        "suitable_as_main": True,
        "suitable_as_parser": True,
        "recommended_level": "B",
        "notes": [
            "DashScope/SiliconFlow Qwen: prefer json_object + output_schema",
            "Disable thinking: chat_template_kwargs.enable_thinking=false",
        ],
    },
    DomesticProvider.GLM: {
        "openai_compatible": True,
        "json_schema_strict": False,
        "json_object_mode": True,
        "function_calling": True,
        "strict_tools": False,
        "streaming_structured": True,
        "thinking_mode_breaks_structured": True,
        "suitable_as_main": True,
        "suitable_as_parser": True,
        "recommended_level": "B",
        "notes": [
            "GLM OpenAI-compatible: use_json_mode=True for Agno output_schema",
            "Disable thinking: extra_body thinking.type=disabled",
        ],
    },
    DomesticProvider.MINIMAX: {
        "openai_compatible": True,
        "json_schema_strict": False,
        "json_object_mode": True,
        "function_calling": True,
        "strict_tools": True,
        "streaming_structured": True,
        "thinking_mode_breaks_structured": False,
        "suitable_as_main": True,
        "suitable_as_parser": True,
        "recommended_level": "B",
        "notes": [
            "MiniMax OpenAI-compatible endpoint; Agno uses system role_map",
            "Often stable with json_object; strict json_schema varies by model",
        ],
    },
    DomesticProvider.OPENAI: {
        "openai_compatible": True,
        "json_schema_strict": True,
        "json_object_mode": True,
        "function_calling": True,
        "strict_tools": True,
        "streaming_structured": True,
        "thinking_mode_breaks_structured": False,
        "suitable_as_main": True,
        "suitable_as_parser": True,
        "recommended_level": "A",
        "notes": ["Official OpenAI endpoint supports native json_schema strict"],
    },
    DomesticProvider.UNKNOWN: {
        "openai_compatible": True,
        "json_schema_strict": False,
        "json_object_mode": True,
        "function_calling": False,
        "strict_tools": False,
        "streaming_structured": False,
        "thinking_mode_breaks_structured": True,
        "suitable_as_main": False,
        "suitable_as_parser": False,
        "recommended_level": "D",
        "notes": ["Unknown provider — default to tool-based fallback (Level D)"],
    },
}


def detect_provider(*, model: str = "", base_url: str = "") -> DomesticProvider:
    """Heuristic provider detection from model name and base URL."""
    haystack = f"{model} {base_url}".lower()
    for provider, hints in _PROVIDER_HINTS.items():
        if any(hint in haystack for hint in hints):
            return provider
    if "openai.com" in haystack:
        return DomesticProvider.OPENAI
    return DomesticProvider.UNKNOWN


def _profile_from_env(role: str = "general") -> LLMProfile:
    return get_llm_profile(role)  # type: ignore[arg-type]


def _build_mock_profile(provider: DomesticProvider, profile: LLMProfile) -> ProviderCapabilityProfile:
    defaults = dict(_MOCK_DEFAULTS[provider])
    notes = list(defaults.pop("notes", []))
    notes.append("Mock profile is an offline heuristic for unit tests/smoke only; not a verified capability signal")
    return ProviderCapabilityProfile(
        provider=provider,
        model=profile.model,
        base_url=profile.base_url,
        probe_mode="mock",
        verified=False,
        mock_only=True,
        notes=notes,
        **defaults,
    )


def _openai_client(profile: LLMProfile):
    import openai

    return openai.OpenAI(
        api_key=profile.api_key,
        base_url=profile.base_url,
        timeout=profile.timeout,
    )


def _probe_json_object(client, model: str, extra_body: dict[str, Any] | None) -> bool:
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": 'Return JSON: {"ok": true}'}],
        "response_format": {"type": "json_object"},
    }
    if extra_body:
        kwargs["extra_body"] = extra_body
    resp = client.chat.completions.create(**kwargs)
    content = (resp.choices[0].message.content or "").strip()
    data = json.loads(content)
    return isinstance(data, dict) and data.get("ok") is True


def _probe_json_schema_strict(client, model: str, extra_body: dict[str, Any] | None) -> bool:
    schema = {
        "type": "object",
        "properties": {"ok": {"type": "boolean"}},
        "required": ["ok"],
        "additionalProperties": False,
    }
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": "Return ok=true"}],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "ProbeSchema",
                "schema": schema,
                "strict": True,
            },
        },
    }
    if extra_body:
        kwargs["extra_body"] = extra_body
    resp = client.chat.completions.create(**kwargs)
    content = (resp.choices[0].message.content or "").strip()
    data = json.loads(content)
    return isinstance(data, dict) and data.get("ok") is True


def _probe_streaming_structured(
    client,
    model: str,
    extra_body: dict[str, Any] | None,
    response_format: dict[str, Any],
) -> bool:
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": 'Return exactly this JSON object: {"ok": true}'}],
        "response_format": response_format,
        "stream": True,
    }
    if extra_body:
        kwargs["extra_body"] = extra_body
    chunks = client.chat.completions.create(**kwargs)
    content_parts: list[str] = []
    for chunk in chunks:
        for choice in getattr(chunk, "choices", []) or []:
            delta = getattr(choice, "delta", None)
            part = getattr(delta, "content", None) if delta is not None else None
            if part:
                content_parts.append(part)
    data = json.loads("".join(content_parts).strip())
    return isinstance(data, dict) and data.get("ok") is True


def _probe_function_calling(client, model: str, extra_body: dict[str, Any] | None) -> tuple[bool, bool]:
    tools = [
        {
            "type": "function",
            "function": {
                "name": "mark_ok",
                "description": "Mark probe success with a constrained payload",
                "parameters": {
                    "type": "object",
                    "properties": {"code": {"type": "string", "enum": ["ok"]}},
                    "required": ["code"],
                    "additionalProperties": False,
                },
                "strict": True,
            },
        }
    ]
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": "Call mark_ok with code=ok. Do not include any extra field even if you want to explain.",
            }
        ],
        "tools": tools,
        "tool_choice": {"type": "function", "function": {"name": "mark_ok"}},
    }
    if extra_body:
        kwargs["extra_body"] = extra_body
    resp = client.chat.completions.create(**kwargs)
    message = resp.choices[0].message
    has_tool = bool(message.tool_calls)
    strict_ok = False
    if has_tool and message.tool_calls:
        args = json.loads(message.tool_calls[0].function.arguments)
        strict_ok = args == {"code": "ok"}
    return has_tool, strict_ok


def _with_thinking(extra_body: dict[str, Any] | None, provider: DomesticProvider, enabled: bool) -> dict[str, Any]:
    merged = dict(extra_body or {})
    if provider == DomesticProvider.QWEN:
        chat_kwargs = dict(merged.get("chat_template_kwargs") or {})
        chat_kwargs["enable_thinking"] = enabled
        merged["chat_template_kwargs"] = chat_kwargs
    elif provider == DomesticProvider.GLM:
        merged["thinking"] = {"type": "enabled" if enabled else "disabled"}
    return merged


def _probe_thinking_mode_breaks_structured(
    client,
    model: str,
    provider: DomesticProvider,
    extra_body: dict[str, Any] | None,
) -> bool:
    if provider not in {DomesticProvider.QWEN, DomesticProvider.GLM}:
        return _thinking_extra_body_present(extra_body)
    off_ok = _probe_json_object(client, model, _with_thinking(extra_body, provider, False))
    on_ok = _probe_json_object(client, model, _with_thinking(extra_body, provider, True))
    return off_ok and not on_ok


def probe_provider_capabilities_live(
    profile: LLMProfile | None = None,
    *,
    role: str = "general",
) -> ProviderCapabilityProfile:
    """Live API probe. Requires valid API key in env."""
    profile = profile or _profile_from_env(role)
    provider = detect_provider(model=profile.model, base_url=profile.base_url)
    errors: list[str] = []

    if not profile.is_complete():
        errors.append("incomplete LLM profile (missing api_key/base_url/model)")
        return ProviderCapabilityProfile(
            provider=provider,
            model=profile.model,
            base_url=profile.base_url,
            openai_compatible=bool(profile.base_url),
            recommended_level="D",
            probe_mode="live",
            verified=False,
            mock_only=False,
            probe_errors=errors,
            notes=["Live probe could not run because the LLM profile is incomplete"],
        )

    client = _openai_client(profile)
    extra_body = profile.extra_body

    json_object_mode = False
    json_schema_strict = False
    function_calling = False
    strict_tools = False
    streaming_structured = False
    thinking_breaks = _thinking_extra_body_present(extra_body)

    try:
        json_object_mode = _probe_json_object(client, profile.model, extra_body)
    except Exception as exc:  # noqa: BLE001 — probe should capture all provider errors
        errors.append(f"json_object: {exc}")

    try:
        json_schema_strict = _probe_json_schema_strict(client, profile.model, extra_body)
    except Exception as exc:
        errors.append(f"json_schema_strict: {exc}")

    try:
        function_calling, strict_tools = _probe_function_calling(client, profile.model, extra_body)
    except Exception as exc:
        errors.append(f"strict_tool_schema: {exc}")

    try:
        if json_schema_strict:
            response_format = {
                "type": "json_schema",
                "json_schema": {
                    "name": "ProbeSchema",
                    "schema": {
                        "type": "object",
                        "properties": {"ok": {"type": "boolean"}},
                        "required": ["ok"],
                        "additionalProperties": False,
                    },
                    "strict": True,
                },
            }
        else:
            response_format = {"type": "json_object"}
        streaming_structured = _probe_streaming_structured(client, profile.model, extra_body, response_format)
    except Exception as exc:
        errors.append(f"streaming_structured: {exc}")

    try:
        thinking_breaks = _probe_thinking_mode_breaks_structured(client, profile.model, provider, extra_body)
    except Exception as exc:
        errors.append(f"thinking_mode: {exc}")

    recommended = _recommend_level(json_schema_strict, json_object_mode, function_calling)

    return ProviderCapabilityProfile(
        provider=provider,
        model=profile.model,
        base_url=profile.base_url,
        openai_compatible=True,
        json_schema_strict=json_schema_strict,
        json_object_mode=json_object_mode,
        function_calling=function_calling,
        strict_tools=strict_tools,
        streaming_structured=streaming_structured,
        thinking_mode_breaks_structured=thinking_breaks,
        suitable_as_main=json_object_mode or json_schema_strict or function_calling,
        suitable_as_parser=json_object_mode or json_schema_strict,
        recommended_level=recommended,
        probe_mode="live",
        verified=True,
        mock_only=False,
        probe_errors=errors,
        notes=_live_notes(provider, json_schema_strict, json_object_mode),
    )


def probe_provider_capabilities(
    profile: LLMProfile | None = None,
    *,
    role: str = "general",
    force_live: bool | None = None,
) -> ProviderCapabilityProfile:
    """Probe provider capabilities. Uses mock defaults unless live probe is enabled."""
    profile = profile or _profile_from_env(role)
    provider = detect_provider(model=profile.model, base_url=profile.base_url)

    use_live = force_live if force_live is not None else _live_probe_enabled()
    if use_live:
        logger.info("Running live structured-output capability probe for %s", provider.value)
        return probe_provider_capabilities_live(profile, role=role)

    logger.debug("Using mock capability profile for %s", provider.value)
    return _build_mock_profile(provider, profile)


def _live_probe_enabled() -> bool:
    return os.getenv(LIVE_PROBE_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def _thinking_extra_body_present(extra_body: dict[str, Any] | None) -> bool:
    if not extra_body:
        return False
    if extra_body.get("thinking"):
        return True
    chat_kwargs = extra_body.get("chat_template_kwargs") or {}
    return bool(chat_kwargs.get("enable_thinking"))


def _recommend_level(json_schema_strict: bool, json_object_mode: bool, function_calling: bool) -> str:
    if json_schema_strict:
        return "A"
    if json_object_mode:
        return "B"
    if function_calling:
        return "D"
    return "D"


def _live_notes(provider: DomesticProvider, json_schema_strict: bool, json_object_mode: bool) -> list[str]:
    notes = [f"Live probe for {provider.value}"]
    if json_schema_strict:
        notes.append("Native json_schema strict supported — use Level A")
    elif json_object_mode:
        notes.append("json_object supported — use Level B with validation")
    else:
        notes.append("Structured modes failed — use Level C/D")
    return notes


def build_capability_matrix(profiles: list[ProviderCapabilityProfile]) -> list[dict[str, Any]]:
    """Build a printable capability matrix from probe results."""
    rows = []
    for p in profiles:
        rows.append(
            {
                "provider": p.provider.value,
                "model": p.model,
                "level_A": p.json_schema_strict,
                "level_B": p.json_object_mode,
                "level_C": p.suitable_as_parser and not p.json_schema_strict,
                "level_D": p.function_calling,
                "recommended": p.recommended_level,
                "main": p.suitable_as_main,
                "parser": p.suitable_as_parser,
                "thinking_breaks": p.thinking_mode_breaks_structured,
                "probe_mode": p.probe_mode,
                "verified": p.verified,
                "mock_only": p.mock_only,
                "probe_errors": p.probe_errors,
            }
        )
    return rows
