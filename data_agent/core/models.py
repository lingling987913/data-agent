from __future__ import annotations

from agno.models.openai import OpenAIChat

from data_agent.core.llm_profiles import (
    LLMProfile,
    OPENAI_COMPAT_ROLE_MAP,
    get_llm_profile,
    is_openai_official_base_url,
    profile_to_openai_chat,
)


def get_lightweight_model(temperature: float | None = None) -> OpenAIChat:
    """Cheap text model: LIGHT_LLM_* when set, else LLM_* (no legacy PARSING_LLM)."""
    profile = get_llm_profile("light_llm")
    model = profile_to_openai_chat(profile)
    if temperature is not None:
        model.temperature = temperature  # type: ignore[attr-defined]
    return model


def get_light_vlm_profile() -> LLMProfile:
    """Light vision profile: LIGHT_VLM_* when set, else VLM_* chain."""
    return get_llm_profile("light_vision")


def get_model(model_id: str | None = None, temperature: float | None = None) -> OpenAIChat:
    profile = get_llm_profile("general")
    effective_model = model_id or profile.model
    kwargs: dict = {"id": effective_model}
    if temperature is not None:
        kwargs["temperature"] = temperature

    if model_id:
        if profile.api_key:
            kwargs["api_key"] = profile.api_key
        if profile.base_url:
            kwargs["base_url"] = profile.base_url
            if not is_openai_official_base_url(profile.base_url):
                kwargs["supports_native_structured_outputs"] = False
        kwargs.setdefault("timeout", int(profile.timeout))
        kwargs.setdefault("max_retries", 3)
        kwargs.setdefault("role_map", OPENAI_COMPAT_ROLE_MAP)
        return OpenAIChat(**kwargs)

    model = profile_to_openai_chat(profile)
    if temperature is not None:
        model.temperature = temperature  # type: ignore[attr-defined]
    return model
