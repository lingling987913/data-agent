"""Centralized LLM endpoint profiles with env-based fallback chains.

User-facing config groups (4):
  LLM_*       — default text model (agents, structuring, etc.)
  VLM_*       — main vision / multimodal (embedded image description)
  LIGHT_LLM_* — optional cheaper text model; parsing/formula prefer this when set
  LIGHT_VLM_* — optional cheaper vision model; OPTIMAL mode tries this before VLM

Deprecated alias: LIGHTWEIGHT_* (text only) — maps to LIGHT_LLM_* chain when LIGHT_LLM_* unset.

Legacy env vars (OPENAI_*, PARSING_LLM_*, PARSING_VISION_LLM_*, PARSING_FORMULA_LLM_*)
remain supported as fallbacks.
"""

from __future__ import annotations

import base64
import json
import logging
import mimetypes
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"
if _ENV_FILE.exists():
    load_dotenv(_ENV_FILE, override=False)

LLMRole = Literal[
    "general",
    "parsing",
    "vision",
    "formula",
    "lightweight",
    "light_llm",
    "light_vision",
]

# Prefix chains: first match wins per field.
_PREFIX_CHAIN: dict[LLMRole, list[str]] = {
    "general": ["LLM", "OPENAI"],
    # parsing/formula/lightweight: LIGHT_LLM → LIGHTWEIGHT (deprecated) → LLM → legacy
    "parsing": ["LIGHT_LLM", "LIGHTWEIGHT", "LLM", "PARSING_LLM", "OPENAI"],
    "vision": ["VLM", "PARSING_VISION_LLM"],
    "formula": ["LIGHT_LLM", "LIGHTWEIGHT", "LLM", "PARSING_FORMULA_LLM", "PARSING_LLM", "OPENAI"],
    "lightweight": ["LIGHT_LLM", "LIGHTWEIGHT", "LLM"],
    "light_llm": ["LIGHT_LLM", "LIGHTWEIGHT", "LLM"],
    "light_vision": ["LIGHT_VLM", "VLM", "PARSING_VISION_LLM"],
}

_DEFAULT_MODEL: dict[LLMRole, str] = {
    "general": "gpt-4o",
    "parsing": "gpt-4o-mini",
    "vision": "",
    "formula": "gpt-4o-mini",
    "lightweight": "gpt-4o-mini",
    "light_llm": "gpt-4o-mini",
    "light_vision": "",
}

_DEFAULT_BASE_URL = "https://api.openai.com/v1"
_DEFAULT_TIMEOUT: dict[LLMRole, float] = {
    "general": 300.0,
    "parsing": 120.0,
    "vision": 30.0,
    "formula": 120.0,
    "lightweight": 120.0,
    "light_llm": 120.0,
    "light_vision": 45.0,
}
_DEFAULT_MAX_TOKENS: dict[LLMRole, int | None] = {
    "general": None,
    "parsing": None,
    "vision": 1200,
    "formula": None,
    "lightweight": None,
    "light_llm": None,
    "light_vision": 900,
}

_LIGHTWEIGHT_DEPRECATED_WARNED = False
_PROFILE_FIELDS = ("API_KEY", "MODEL_NAME", "BASE_URL", "TIMEOUT_SECONDS", "MAX_TOKENS", "EXTRA_BODY")


@dataclass(frozen=True)
class LLMProfile:
    role: LLMRole
    model: str
    api_key: str
    base_url: str
    timeout: float = 120.0
    max_tokens: int | None = None
    extra_body: dict[str, Any] | None = None

    def is_complete(self) -> bool:
        return bool(self.api_key and self.base_url and self.model)


def _env(key: str, default: str = "") -> str:
    return (os.getenv(key) or default).strip()


def _first_env(*keys: str, default: str = "") -> str:
    for key in keys:
        value = _env(key)
        if value:
            return value
    return default


def _prefix_keys(prefixes: list[str], field: str) -> list[str]:
    return [f"{prefix}_{field}" for prefix in prefixes]


def _maybe_warn_lightweight_deprecated(role: LLMRole) -> None:
    global _LIGHTWEIGHT_DEPRECATED_WARNED
    if _LIGHTWEIGHT_DEPRECATED_WARNED:
        return
    if "LIGHTWEIGHT" not in _PREFIX_CHAIN[role]:
        return
    has_light_llm = any(_env(f"LIGHT_LLM_{field}") for field in _PROFILE_FIELDS)
    has_lightweight = any(_env(f"LIGHTWEIGHT_{field}") for field in _PROFILE_FIELDS)
    if has_lightweight and not has_light_llm:
        logger.warning(
            "[llm_profiles] LIGHTWEIGHT_* is deprecated; migrate to LIGHT_LLM_* (text) "
            "and LIGHT_VLM_* (vision). LIGHTWEIGHT_* will continue to work as a text alias."
        )
        _LIGHTWEIGHT_DEPRECATED_WARNED = True


def _resolve_from_chain(role: LLMRole, field: str) -> str:
    return _first_env(*_prefix_keys(_PREFIX_CHAIN[role], field))


def _resolve_model(role: LLMRole) -> str:
    keys = _prefix_keys(_PREFIX_CHAIN[role], "MODEL_NAME")
    return _first_env(*keys, default=_DEFAULT_MODEL[role])


def _resolve_base_url(role: LLMRole) -> str:
    url = _resolve_from_chain(role, "BASE_URL")
    if url:
        return url.rstrip("/")
    return _DEFAULT_BASE_URL if role == "general" else ""


def _resolve_extra_body(role: LLMRole) -> dict[str, Any] | None:
    for prefix in _PREFIX_CHAIN[role]:
        parsed = _parse_extra_body(prefix)
        if parsed is not None:
            return parsed
    return None


_INVALID_EXTRA_BODY_LOGGED: set[str] = set()


def _parse_extra_body(prefix: str) -> dict[str, Any] | None:
    raw = _env(f"{prefix}_EXTRA_BODY")
    if not raw or not str(raw).strip():
        return None
    stripped = str(raw).strip()
    if stripped.lower() in {"none", "null", "false", "0", "{}"}:
        return None
    candidates = [stripped]
    if len(stripped) >= 2 and stripped[0] == stripped[-1] and stripped[0] in "\"'":
        candidates.append(stripped[1:-1])
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
        return None
    if prefix not in _INVALID_EXTRA_BODY_LOGGED:
        _INVALID_EXTRA_BODY_LOGGED.add(prefix)
        logger.warning("[llm_profiles] invalid %s_EXTRA_BODY JSON, ignored", prefix)
    return None


def _parse_float_env(key: str, default: float) -> float:
    raw = _env(key)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning("[llm_profiles] invalid %s=%r, using default %s", key, raw, default)
        return default


def _parse_int_env(key: str, default: int | None) -> int | None:
    raw = _env(key)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("[llm_profiles] invalid %s=%r, using default %s", key, raw, default)
        return default


def _resolve_timeout(role: LLMRole) -> float:
    for prefix in _PREFIX_CHAIN[role]:
        raw = _env(f"{prefix}_TIMEOUT_SECONDS")
        if raw:
            return _parse_float_env(f"{prefix}_TIMEOUT_SECONDS", _DEFAULT_TIMEOUT[role])
    return _DEFAULT_TIMEOUT[role]


def _resolve_max_tokens(role: LLMRole) -> int | None:
    for prefix in _PREFIX_CHAIN[role]:
        raw = _env(f"{prefix}_MAX_TOKENS")
        if raw:
            return _parse_int_env(f"{prefix}_MAX_TOKENS", _DEFAULT_MAX_TOKENS[role])
    return _DEFAULT_MAX_TOKENS[role]


def resolve_profile_env_prefix(role: LLMRole) -> str | None:
    """Return the first env prefix in the role chain that has any configured value."""
    for prefix in _PREFIX_CHAIN[role]:
        if any(_env(f"{prefix}_{field}") for field in _PROFILE_FIELDS):
            return prefix
    return None


def get_llm_profile(role: LLMRole) -> LLMProfile:
    _maybe_warn_lightweight_deprecated(role)
    return LLMProfile(
        role=role,
        model=_resolve_model(role),
        api_key=_resolve_from_chain(role, "API_KEY"),
        base_url=_resolve_base_url(role),
        timeout=_resolve_timeout(role),
        max_tokens=_resolve_max_tokens(role),
        extra_body=_resolve_extra_body(role),
    )


# agno OpenAIChat defaults map system→developer (OpenAI o-series). Most OpenAI-compatible
# providers (MiniMax, SiliconFlow, etc.) only accept system/user/assistant/tool.
OPENAI_COMPAT_ROLE_MAP: dict[str, str] = {
    "system": "system",
    "user": "user",
    "assistant": "assistant",
    "tool": "tool",
    "model": "assistant",
}


def is_openai_official_base_url(base_url: str) -> bool:
    url = (base_url or "").lower().rstrip("/")
    return url.endswith("api.openai.com/v1")


def profile_to_openai_chat(profile: LLMProfile):
    from agno.models.openai import OpenAIChat

    kwargs: dict[str, Any] = {
        "id": profile.model,
        "timeout": int(profile.timeout),
        "max_retries": 3,
        "role_map": OPENAI_COMPAT_ROLE_MAP,
    }
    if profile.api_key:
        kwargs["api_key"] = profile.api_key
    if profile.base_url:
        kwargs["base_url"] = profile.base_url
    if profile.max_tokens is not None:
        kwargs["max_tokens"] = profile.max_tokens
    if profile.extra_body:
        kwargs["extra_body"] = profile.extra_body
    if profile.base_url and not is_openai_official_base_url(profile.base_url):
        kwargs["supports_native_structured_outputs"] = False
    return OpenAIChat(**kwargs)


def _image_data_url(image_path: str) -> str:
    mime, _ = mimetypes.guess_type(image_path)
    mime = mime or "image/jpeg"
    with open(image_path, "rb") as handle:
        encoded = base64.b64encode(handle.read()).decode()
    return f"data:{mime};base64,{encoded}"


def _minimax_vlm_url(base_url: str) -> str:
    root = (base_url or "").rstrip("/")
    if root.endswith("/v1"):
        return f"{root}/coding_plan/vlm"
    return f"{root}/v1/coding_plan/vlm"


def _extract_text_from_payload(payload: Any) -> str:
    if isinstance(payload, str):
        return payload.strip()
    if isinstance(payload, list):
        for item in payload:
            text = _extract_text_from_payload(item)
            if text:
                return text
        return ""
    if not isinstance(payload, dict):
        return ""

    for key in ("text", "content", "description", "output", "result", "message"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        text = _extract_text_from_payload(value)
        if text:
            return text

    choices = payload.get("choices")
    if isinstance(choices, list):
        for choice in choices:
            text = _extract_text_from_payload(choice)
            if text:
                return text
    return ""


def minimax_vlm_describe_image(profile: LLMProfile, image_path: str, prompt: str) -> str | None:
    """MiniMax dedicated image understanding API for text models like MiniMax-M2.x."""
    if not profile.is_complete():
        return None

    import requests

    response = requests.post(
        _minimax_vlm_url(profile.base_url),
        headers={
            "Authorization": f"Bearer {profile.api_key}",
            "Content-Type": "application/json",
        },
        json={
            "prompt": prompt,
            "image_url": _image_data_url(image_path),
        },
        timeout=profile.timeout,
    )
    response.raise_for_status()
    text = _extract_text_from_payload(response.json())
    return text or None


def vision_describe_image(profile: LLMProfile, image_path: str, prompt: str) -> str | None:
    """Multimodal chat completion for a local image file."""
    if not profile.is_complete():
        return None

    import openai

    client = openai.OpenAI(
        api_key=profile.api_key,
        base_url=profile.base_url,
        timeout=profile.timeout,
    )
    create_kwargs: dict[str, Any] = {
        "model": profile.model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": _image_data_url(image_path)},
                    },
                ],
            }
        ],
    }
    if profile.max_tokens is not None:
        create_kwargs["max_tokens"] = profile.max_tokens
    if profile.extra_body:
        create_kwargs["extra_body"] = profile.extra_body

    resp = client.chat.completions.create(**create_kwargs)
    if not resp.choices:
        return None
    content = (resp.choices[0].message.content or "").strip()
    return content or None
