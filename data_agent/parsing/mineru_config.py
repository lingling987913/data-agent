"""Central MinerU configuration and online route selection.

Reads ``MINERU_*`` env vars once per call site and resolves which online API
(agent lightweight vs v4 extract) should run first for a given file.
"""

from __future__ import annotations

import logging
import os
from typing import Literal

logger = logging.getLogger(__name__)

MinerURoute = Literal["agent", "extract"]

_LEGACY_TOKEN_ENV = "MINERU_API_TOKEN"
_TOKEN_ENV = "MINERU_AGENT_API_TOKEN"


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def get_mineru_api_mode() -> str:
    return os.getenv("MINERU_API_MODE", "").strip().lower()


def mineru_token() -> str:
    return (os.getenv(_TOKEN_ENV) or os.getenv(_LEGACY_TOKEN_ENV) or "").strip()


def mineru_online_disabled() -> bool:
    return get_mineru_api_mode() in {"disabled", "off", "local_only"}


def mineru_agent_enabled() -> bool:
    """True when Agent lightweight API may be invoked."""
    if mineru_online_disabled():
        return False
    mode = get_mineru_api_mode()
    if mode in {"agent", "agent_only", "agent_light", "light", "online_agent"}:
        return True
    return _env_bool("MINERU_AGENT_API_ENABLED", False)


def mineru_extract_available() -> bool:
    """True when v4 extract API credentials and switch allow calls."""
    if mineru_online_disabled():
        return False
    if not mineru_token():
        return False
    return _env_bool("MINERU_EXTRACT_API_ENABLED", True)


def mineru_extract_enabled() -> bool:
    """True when v4 extract may be chosen as the primary online parser."""
    if not mineru_extract_available():
        return False
    mode = get_mineru_api_mode()
    return mode not in {"agent_only", "agent"}


def mineru_local_enabled() -> bool:
    return _env_bool("MINERU_LOCAL_ENABLED", False)


def mineru_prefer_local() -> bool:
    """When True, try local MinerU HTTP before online APIs (default: on if local enabled)."""
    if not mineru_local_enabled():
        return False
    raw = os.getenv("MINERU_LOCAL_FIRST")
    if raw is None:
        return True
    return _env_bool("MINERU_LOCAL_FIRST", True)


def mineru_online_configured() -> bool:
    """True when any MinerU online or local path is configured."""
    if mineru_online_disabled() and not mineru_local_enabled():
        return False
    return bool(
        mineru_token()
        or mineru_agent_enabled()
        or mineru_extract_available()
        or mineru_local_enabled()
        or _env_bool("MINERU_AGENT_IS_OCR")
    )


def _prefer_extract_for_file(file_path: str, file_name: str) -> bool:
    from data_agent.parsing.parsers.mineru_extract_parser import should_prefer_mineru_extract

    return should_prefer_mineru_extract(file_path, file_name)


def resolve_online_parse_order(file_path: str, file_name: str) -> list[MinerURoute]:
    """Return ordered online routes (``agent`` / ``extract``) for this file."""
    if mineru_online_disabled():
        return []

    mode = get_mineru_api_mode()
    agent_ok = mineru_agent_enabled()
    extract_ok = mineru_extract_available()

    if mode in {"extract", "v4", "precise", "standard"}:
        order: list[MinerURoute] = []
        if extract_ok:
            order.append("extract")
        if agent_ok:
            order.append("agent")
        return order

    if mode in {"agent_only", "agent", "agent_light", "light", "online_agent"}:
        return ["agent"] if agent_ok else []

    prefer_extract = _prefer_extract_for_file(file_path, file_name)
    if prefer_extract:
        order = []
        if extract_ok:
            order.append("extract")
        if agent_ok:
            order.append("agent")
        return order

    order = []
    if agent_ok:
        order.append("agent")
    if extract_ok:
        order.append("extract")
    return order


def describe_online_route(file_path: str, file_name: str) -> str:
    mode = get_mineru_api_mode() or "auto"
    order = resolve_online_parse_order(file_path, file_name)
    if not order:
        return f"mode={mode} online=disabled"
    return f"mode={mode} order={' -> '.join(order)}"


def log_online_route_decision(file_path: str, file_name: str, *, context: str = "") -> None:
    prefix = f"[MinerU] {context}: " if context else "[MinerU] "
    logger.info("%sroute %s", prefix, describe_online_route(file_path, file_name))


__all__ = [
    "MinerURoute",
    "describe_online_route",
    "get_mineru_api_mode",
    "log_online_route_decision",
    "mineru_agent_enabled",
    "mineru_extract_available",
    "mineru_extract_enabled",
    "mineru_local_enabled",
    "mineru_prefer_local",
    "mineru_online_configured",
    "mineru_online_disabled",
    "mineru_token",
    "resolve_online_parse_order",
]
