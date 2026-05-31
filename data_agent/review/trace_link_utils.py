"""Shared helpers for requirement trace link collections."""

from __future__ import annotations

from typing import Any


def _link_status(link: Any) -> str:
    if hasattr(link, "status"):
        return str(link.status or "candidate")
    if isinstance(link, dict):
        return str(link.get("status") or "candidate")
    return "candidate"


def active_trace_links(links: list[Any]) -> list[Any]:
    """Return trace links that are not rejected."""
    return [link for link in links if _link_status(link) != "rejected"]
