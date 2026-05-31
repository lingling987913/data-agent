"""OpenAI SDK wrapper for structuring / self-healing LLM calls."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_BACKOFF_BASE_SEC = 1.0


class StructuringLLMError(RuntimeError):
    """Raised when structuring LLM is unavailable or all retries failed."""


def get_openai_api_key(profile_role: str = "parsing") -> str:
    from data_agent.core.llm_profiles import get_llm_profile

    return get_llm_profile(profile_role).api_key  # type: ignore[arg-type]


def get_openai_base_url(profile_role: str = "parsing") -> str:
    from data_agent.core.llm_profiles import get_llm_profile

    profile = get_llm_profile(profile_role)  # type: ignore[arg-type]
    return profile.base_url or "https://api.openai.com/v1"


def get_default_model_name(profile_role: str = "parsing") -> str:
    from data_agent.core.llm_profiles import get_llm_profile

    return get_llm_profile(profile_role).model or "gpt-4o-mini"  # type: ignore[arg-type]


def _resolve_model_id(model_id: str | None, profile_role: str = "parsing") -> str:
    return (model_id or "").strip() or get_default_model_name(profile_role)


def _require_api_key(profile_role: str = "parsing") -> str:
    api_key = get_openai_api_key(profile_role)
    if not api_key:
        raise StructuringLLMError(
            f"LLM API key not configured for profile {profile_role!r}. Set LIGHT_LLM_* or LLM_* "
            "(legacy LIGHTWEIGHT_* / OPENAI_* / PARSING_LLM_* also work)."
        )
    return api_key


def _profile_extra_body(profile_role: str = "parsing") -> dict[str, Any] | None:
    from data_agent.core.llm_profiles import get_llm_profile

    return get_llm_profile(profile_role).extra_body  # type: ignore[arg-type]


async def complete_text(
    system: str,
    user: str,
    *,
    model_id: str | None = None,
    temperature: float = 0.0,
    max_tokens: int = 4096,
    timeout_sec: float | None = None,
    profile_role: str = "parsing",
) -> str:
    """Call chat completions (non-streaming) with retries and exponential backoff."""
    api_key = _require_api_key(profile_role)
    base_url = get_openai_base_url(profile_role)
    model = _resolve_model_id(model_id, profile_role)
    extra_body = _profile_extra_body(profile_role)
    if timeout_sec is None:
        from data_agent.core.config import get_structuring_llm_timeout

        timeout_sec = float(get_structuring_llm_timeout())

    last_exc: Exception | None = None
    for attempt in range(_MAX_RETRIES):
        try:
            return await _call_once(
                api_key=api_key,
                base_url=base_url,
                model=model,
                system=system,
                user=user,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout_sec=timeout_sec,
                extra_body=extra_body,
            )
        except StructuringLLMError:
            raise
        except Exception as exc:
            last_exc = exc
            if attempt < _MAX_RETRIES - 1:
                delay = _BACKOFF_BASE_SEC * (2**attempt)
                logger.warning(
                    "[structuring/llm] attempt %s/%s failed: %s; retry in %.1fs",
                    attempt + 1,
                    _MAX_RETRIES,
                    exc,
                    delay,
                )
                await asyncio.sleep(delay)

    raise StructuringLLMError(
        f"LLM call failed after {_MAX_RETRIES} attempts: {last_exc}"
    ) from last_exc


async def _call_once(
    *,
    api_key: str,
    base_url: str,
    model: str,
    system: str,
    user: str,
    temperature: float,
    max_tokens: int,
    timeout_sec: float,
    extra_body: dict[str, Any] | None = None,
) -> str:
    import openai

    client = openai.OpenAI(
        api_key=api_key,
        base_url=base_url,
        timeout=timeout_sec,
    )
    create_kwargs: dict[str, Any] = {
        "model": model,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    if extra_body:
        create_kwargs["extra_body"] = extra_body

    def _sync_create() -> str:
        resp = client.chat.completions.create(**create_kwargs)
        if not resp.choices:
            return ""
        return (resp.choices[0].message.content or "").strip()

    loop = asyncio.get_event_loop()
    started = time.perf_counter()
    content = await loop.run_in_executor(None, _sync_create)
    logger.debug(
        "[structuring/llm] model=%s latency_ms=%.0f chars=%d",
        model,
        (time.perf_counter() - started) * 1000,
        len(content),
    )
    return content


def estimate_tokens(text: str) -> int:
    """Rough token estimate (chars / 4) for stats."""
    return max(1, len(text) // 4)
