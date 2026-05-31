"""Shared helpers for figure/image block text normalization."""

from __future__ import annotations

import re

_IMAGE_MD_RE = re.compile(r"!\[[^\]]*\]\([^)]+\)")
_IMAGE_PATH_RE = re.compile(
    r"(?:^|/)(?:images/)?[^/\s]+\.(?:jpe?g|png|gif|webp|bmp|jp2)(?:\?[^/\s]*)?$",
    re.IGNORECASE,
)


def looks_like_image_ref(value: str) -> bool:
    text = (value or "").strip()
    if not text:
        return False
    if _IMAGE_MD_RE.search(text):
        return True
    lowered = text.lower()
    if lowered in {"image", "figure", "img", "photo", "picture"}:
        return False
    return bool(_IMAGE_PATH_RE.search(text))


__all__ = ["looks_like_image_ref"]
