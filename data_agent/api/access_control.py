"""Configurable API exposure tiers: competition public, optional demo, internal-only."""

from __future__ import annotations

import ipaddress
import logging
import os
import re
from enum import Enum

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response

logger = logging.getLogger(__name__)

_DEFAULT_DEV_TOKEN = "dev-token-change-me"

# RFC1918 + loopback + link-local; testclient for ASGI tests when scope != full
_PRIVATE_NETWORKS = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
)
_INTERNAL_HOST_ALIASES = frozenset({"localhost"})

_DOC_PATHS = frozenset({"/docs", "/redoc", "/openapi.json"})

_PUBLIC_EXACT: frozenset[tuple[str, str]] = frozenset(
    {
        ("GET", "/health"),
        ("POST", "/api/v1/task/submit"),
    }
)
_PUBLIC_PREFIXES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("GET", re.compile(r"^/api/v1/task/status/[^/]+$")),
    ("GET", re.compile(r"^/api/v1/task/result/[^/]+$")),
)
_DEMO_EXACT: frozenset[tuple[str, str]] = frozenset(
    {
        ("GET", "/api/v1/structuring/modes"),
        ("POST", "/api/v1/parsing/parse"),
        ("GET", "/api/v1/super-agent/capabilities"),
    }
)


class RouteTier(str, Enum):
    PUBLIC = "public"
    PUBLIC_DEMO = "public_demo"
    INTERNAL = "internal"


def get_expose_scope() -> str:
    """full | competition | demo — also accepts API_PUBLIC_MODE alias."""
    raw = os.getenv("API_EXPOSE_SCOPE") or os.getenv("API_PUBLIC_MODE") or "full"
    return raw.strip().lower()


def is_public_exposure_scope() -> bool:
    return get_expose_scope() in {"competition", "demo"}


def classify_route(method: str, path: str) -> RouteTier:
    method = method.upper()
    path = (path.split("?")[0] or "/").rstrip("/") or "/"

    if path in _DOC_PATHS:
        return RouteTier.INTERNAL

    if (method, path) in _PUBLIC_EXACT:
        return RouteTier.PUBLIC
    for verb, pattern in _PUBLIC_PREFIXES:
        if method == verb and pattern.match(path):
            return RouteTier.PUBLIC
    if (method, path) in _DEMO_EXACT:
        return RouteTier.PUBLIC_DEMO
    return RouteTier.INTERNAL


def tier_allowed_for_scope(tier: RouteTier, scope: str) -> bool:
    if scope == "full":
        return True
    if scope == "competition":
        return tier == RouteTier.PUBLIC
    if scope == "demo":
        return tier in {RouteTier.PUBLIC, RouteTier.PUBLIC_DEMO}
    logger.warning("Unknown API_EXPOSE_SCOPE=%r; treating as full", scope)
    return True


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host or ""
    return ""


def _ip_is_private(host: str) -> bool:
    if not host:
        return False
    if host in _INTERNAL_HOST_ALIASES:
        return True
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False
    return any(addr in net for net in _PRIVATE_NETWORKS)


def is_internal_request(request: Request) -> bool:
    if _ip_is_private(client_ip(request)):
        return True
    expected = (os.getenv("INTERNAL_API_TOKEN") or "").strip()
    if not expected:
        return False
    for header in ("x-internal-request", "x-internal-token"):
        if request.headers.get(header, "").strip() == expected:
            return True
    return False


def warn_default_api_token_if_public() -> None:
    if not is_public_exposure_scope():
        return
    token = os.getenv("API_TOKEN", _DEFAULT_DEV_TOKEN)
    if token == _DEFAULT_DEV_TOKEN:
        logger.warning(
            "API_EXPOSE_SCOPE is %s but API_TOKEN is still the default %r; "
            "set a strong API_TOKEN before exposing this instance to the internet",
            get_expose_scope(),
            _DEFAULT_DEV_TOKEN,
        )


class ApiAccessControlMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        scope = get_expose_scope()
        if scope == "full":
            return await call_next(request)

        if request.method.upper() == "OPTIONS":
            return await call_next(request)

        tier = classify_route(request.method, request.url.path)
        if tier_allowed_for_scope(tier, scope):
            return await call_next(request)
        if is_internal_request(request):
            return await call_next(request)

        return JSONResponse(
            status_code=403,
            content={
                "detail": "This endpoint is not exposed on the public API; "
                "use an internal network client or internal credentials",
            },
        )
