"""Startup connectivity probes for configured LLM profiles and optional MinerU Agent."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlparse

import requests

from data_agent.core.llm_profiles import LLMProfile, LLMRole, get_llm_profile, resolve_profile_env_prefix

logger = logging.getLogger(__name__)

ProbeStatus = Literal["ok", "failed", "skipped"]

_DEFAULT_PROBE_TIMEOUT_SECONDS = 8.0

_STARTUP_ROLES: tuple[tuple[LLMRole, str], ...] = (
    ("general", "LLM profile"),
    ("light_llm", "LIGHT_LLM"),
    ("vision", "VLM"),
    ("light_vision", "LIGHT_VLM"),
)

_STARTUP_ROLE_LABELS = dict(_STARTUP_ROLES)
_VISION_CAPABLE_MODEL_HINTS = (
    "vl",
    "qwen-vl",
    "qwen2.5-vl",
    "qwen3-vl",
    "vision",
    "visual",
    "multimodal",
    "gpt-4o",
    "gpt-4.1",
    "gemini",
    "claude-3",
)


@dataclass(frozen=True)
class ProfileProbeResult:
    role: LLMRole
    label: str
    env_prefix: str | None
    model: str
    base_url_display: str
    status: ProbeStatus
    detail: str


@dataclass(frozen=True)
class MinerUAgentProbeResult:
    configured: bool
    base_url_display: str
    status: ProbeStatus
    detail: str


def format_base_url_for_log(base_url: str) -> str:
    """Strip scheme for compact logs; mask embedded credentials if present."""
    raw = (base_url or "").strip().rstrip("/")
    if not raw:
        return ""
    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    host = parsed.netloc or parsed.path.split("/")[0]
    path = parsed.path if parsed.netloc else "/" + "/".join(parsed.path.split("/")[1:])
    path = path.rstrip("/")
    display = f"{host}{path}" if path and path != "/" else host
    if parsed.username:
        display = display.replace(parsed.username, "****")
    return display


def mask_secret(value: str, secret: str) -> str:
    if not value or not secret or len(secret) < 4:
        return value
    return value.replace(secret, f"{secret[:4]}****")


def _profile_uses_minimax_m2_text_api(profile: LLMProfile) -> bool:
    model = (profile.model or "").lower()
    base_url = (profile.base_url or "").lower()
    return model.startswith("minimax-m2") and "minimax" in base_url


def _profile_supports_image_desc(profile: LLMProfile) -> bool:
    if _profile_uses_minimax_m2_text_api(profile):
        return True
    model = (profile.model or "").lower()
    return any(hint in model for hint in _VISION_CAPABLE_MODEL_HINTS)


def probe_openai_compatible_profile(
    profile: LLMProfile,
    *,
    timeout: float = _DEFAULT_PROBE_TIMEOUT_SECONDS,
    session: requests.Session | None = None,
) -> tuple[ProbeStatus, str]:
    if not profile.is_complete():
        return "skipped", "未配置 API Key / Base URL / Model"

    http = session or requests
    headers = {"Authorization": f"Bearer {profile.api_key}"}
    base = profile.base_url.rstrip("/")

    try:
        response = http.get(f"{base}/models", headers=headers, timeout=timeout)
        if response.status_code == 401:
            return "failed", "GET /models → HTTP 401 认证失败"
        if 200 <= response.status_code < 300:
            return "ok", f"GET /models → HTTP {response.status_code}"
        models_error = f"GET /models → HTTP {response.status_code}"
    except requests.RequestException as exc:
        models_error = str(exc)

    chat_headers = {**headers, "Content-Type": "application/json"}
    payload: dict = {
        "model": profile.model,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 1,
    }
    if profile.extra_body:
        payload.update(profile.extra_body)

    try:
        response = http.post(
            f"{base}/chat/completions",
            headers=chat_headers,
            json=payload,
            timeout=timeout,
        )
        if response.status_code == 401:
            return "failed", "POST /chat/completions → HTTP 401 认证失败"
        if response.status_code < 500:
            return "ok", f"POST /chat/completions → HTTP {response.status_code}"
        return "failed", f"POST /chat/completions → HTTP {response.status_code}"
    except requests.RequestException as exc:
        return "failed", f"{models_error}; chat: {exc}"


def probe_llm_profile(
    role: LLMRole,
    *,
    timeout: float = _DEFAULT_PROBE_TIMEOUT_SECONDS,
    session: requests.Session | None = None,
) -> ProfileProbeResult:
    profile = get_llm_profile(role)
    prefix = resolve_profile_env_prefix(role)
    base_display = format_base_url_for_log(profile.base_url)
    status, detail = probe_openai_compatible_profile(profile, timeout=timeout, session=session)
    if role in {"vision", "light_vision"} and profile.is_complete() and not _profile_supports_image_desc(profile):
        detail = f"{detail}；模型可能不支持图片输入: {profile.model}"
    return ProfileProbeResult(
        role=role,
        label=_STARTUP_ROLE_LABELS.get(role, role),
        env_prefix=prefix,
        model=profile.model or "(未设置)",
        base_url_display=base_display or "(未设置)",
        status=status,
        detail=detail,
    )


def _mineru_agent_token() -> str:
    from data_agent.parsing.mineru_config import mineru_token

    return mineru_token()


def _mineru_agent_base_url() -> str:
    default = "https://mineru.net/api/v1/agent"
    return (
        os.getenv("MINERU_AGENT_API_BASE") or os.getenv("MINERU_API_BASE") or default
    ).rstrip("/")


def probe_mineru_agent(
    *,
    timeout: float = _DEFAULT_PROBE_TIMEOUT_SECONDS,
    session: requests.Session | None = None,
) -> MinerUAgentProbeResult:
    token = _mineru_agent_token()
    base = _mineru_agent_base_url()
    display = format_base_url_for_log(base)
    http = session or requests
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    detail_suffix = "（Agent 轻量 API 无需 Token）" if not token else ""
    try:
        response = http.get(base, headers=headers, timeout=timeout, allow_redirects=True)
        if response.status_code < 500:
            return MinerUAgentProbeResult(
                configured=bool(token),
                base_url_display=display,
                status="ok",
                detail=f"GET → HTTP {response.status_code}{detail_suffix}",
            )
        return MinerUAgentProbeResult(
            configured=bool(token),
            base_url_display=display,
            status="failed",
            detail=f"GET → HTTP {response.status_code}",
        )
    except requests.RequestException as exc:
        return MinerUAgentProbeResult(
            configured=bool(token),
            base_url_display=display,
            status="failed",
            detail=str(exc),
        )


def _format_profile_log_line(result: ProfileProbeResult) -> str:
    prefix_hint = f" [{result.env_prefix}_*]" if result.env_prefix else ""
    endpoint = (
        f"{result.model} @ {result.base_url_display}"
        if result.base_url_display != "(未设置)"
        else result.model
    )
    status_text = {"ok": "ok", "failed": "failed", "skipped": "skipped"}[result.status]
    line = f"[startup] {result.label}{prefix_hint}: {endpoint} → {status_text}"
    if result.status == "failed":
        line = f"{line} ({result.detail})"
    elif result.status == "skipped":
        line = f"{line} ({result.detail})"
    return line


def _log_profile_result(result: ProfileProbeResult) -> None:
    line = _format_profile_log_line(result)
    if result.status == "failed":
        logger.warning(line)
    else:
        logger.info(line)


def _log_mineru_agent_result(result: MinerUAgentProbeResult) -> None:
    status_text = {"ok": "ok", "failed": "failed", "skipped": "skipped"}[result.status]
    line = f"[startup] MinerU Agent @ {result.base_url_display} → {status_text}"
    if result.status != "ok":
        line = f"{line} ({result.detail})"
    if result.status == "failed":
        logger.warning(line)
    else:
        logger.info(line)


def run_startup_checks(
    *,
    probe_timeout: float = _DEFAULT_PROBE_TIMEOUT_SECONDS,
    session: requests.Session | None = None,
) -> list[ProfileProbeResult]:
    """Probe configured LLM profiles and optional MinerU Agent; log human-readable lines."""
    results: list[ProfileProbeResult] = []
    for role, _label in _STARTUP_ROLES:
        result = probe_llm_profile(role, timeout=probe_timeout, session=session)
        results.append(result)
        _log_profile_result(result)

    mineru = probe_mineru_agent(timeout=probe_timeout, session=session)
    _log_mineru_agent_result(mineru)
    return results


__all__ = [
    "MinerUAgentProbeResult",
    "ProfileProbeResult",
    "format_base_url_for_log",
    "mask_secret",
    "probe_llm_profile",
    "probe_mineru_agent",
    "probe_openai_compatible_profile",
    "run_startup_checks",
]
