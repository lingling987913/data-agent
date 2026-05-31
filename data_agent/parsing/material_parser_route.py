"""Unified material parser routing for all ingestion entry points.

Office formats default to local parsers; PDF/images use auto (MinerU chain) unless
the user explicitly selects mineru_agent. PDF routing behavior is unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

OFFICE_LOCAL_EXTENSIONS = {
    ".doc",
    ".docx",
    ".xlsx",
    ".xls",
    ".csv",
    ".ppt",
    ".pptx",
}

PDF_IMAGE_EXTENSIONS = {
    ".pdf",
    ".png",
    ".jpg",
    ".jpeg",
    ".jp2",
    ".webp",
    ".gif",
    ".bmp",
}

_LOCAL_MINERU_EXTENSIONS = PDF_IMAGE_EXTENSIONS

_EXPLICIT_ONLINE_PARSERS = {"mineru_agent", "mineru_via_pdf"}


@dataclass(frozen=True)
class MaterialParserRoute:
    parser_type: str
    processing_mode: str | None
    reason: str
    warning: str = ""


def resolve_material_parser_route(
    file_name: str,
    parser_type: str | None = "auto",
    processing_mode: str | None = None,
) -> MaterialParserRoute:
    """Return the effective parser_type and traceable reason for one material."""
    ext = Path(file_name or "").suffix.lower()
    requested = (parser_type or "auto").strip().lower()
    mode = processing_mode

    if requested in _EXPLICIT_ONLINE_PARSERS:
        return MaterialParserRoute(
            parser_type="mineru_agent",
            processing_mode=mode,
            reason=f"explicit_online:{requested}",
        )

    if requested == "mineru":
        if ext in _LOCAL_MINERU_EXTENSIONS:
            return MaterialParserRoute(
                parser_type="mineru",
                processing_mode=mode,
                reason="explicit_local_mineru",
            )
        return MaterialParserRoute(
            parser_type="local",
            processing_mode=mode,
            reason="mineru_unsupported_office",
            warning=f"MinerU 本地仅支持 PDF/图片，{ext or 'unknown'} 已回退本地解析。",
        )

    if ext in OFFICE_LOCAL_EXTENSIONS:
        return MaterialParserRoute(
            parser_type="local",
            processing_mode=mode,
            reason="office_default_local",
        )

    if ext in PDF_IMAGE_EXTENSIONS:
        if requested in {"", "auto"}:
            return MaterialParserRoute(
                parser_type="auto",
                processing_mode=mode,
                reason="pdf_image_auto",
            )
        if requested == "local":
            return MaterialParserRoute(
                parser_type="local",
                processing_mode=mode,
                reason="pdf_image_explicit_local",
            )
        return MaterialParserRoute(
            parser_type=requested,
            processing_mode=mode,
            reason=f"pdf_image_explicit:{requested}",
        )

    if requested in {"", "auto"}:
        return MaterialParserRoute(
            parser_type="local",
            processing_mode=mode,
            reason="default_local",
        )

    return MaterialParserRoute(
        parser_type=requested,
        processing_mode=mode,
        reason=f"explicit:{requested}",
    )


__all__ = [
    "MaterialParserRoute",
    "OFFICE_LOCAL_EXTENSIONS",
    "PDF_IMAGE_EXTENSIONS",
    "resolve_material_parser_route",
]
