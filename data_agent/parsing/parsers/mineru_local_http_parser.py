"""MinerU local HTTP service adapter.

Calls a self-hosted MinerU FastAPI service (``POST /file_parse``) and converts
the returned Markdown into the same ParsedDocument shape used elsewhere.
"""

from __future__ import annotations

import os
import json
import uuid
from pathlib import Path

import requests

from data_agent.parsing.schemas import ParsedDocument, ParsedDocumentBlock
from data_agent.parsing.parsers.mineru_agent_parser import (
    markdown_to_parsed_blocks,
    normalize_mineru_markdown,
)

_SUPPORTED_EXTENSIONS = {
    ".pdf",
    ".png",
    ".jpg",
    ".jpeg",
    ".jp2",
    ".webp",
    ".gif",
    ".bmp",
}
_DEFAULT_BASE_URL = "http://192.168.168.103:8000"
_local_health_cache: dict | None = None
_local_health_checked_at: float = 0.0


def _health_cache_ttl_seconds() -> float:
    raw = os.getenv("MINERU_LOCAL_HEALTH_CACHE_SECONDS", "30")
    try:
        return max(1.0, float(raw))
    except ValueError:
        return 30.0


def mineru_local_reachable(*, force_refresh: bool = False) -> bool:
    """Return whether local MinerU HTTP is reachable; cache probe briefly."""
    import time

    global _local_health_cache, _local_health_checked_at
    if not mineru_local_enabled():
        return False
    now = time.time()
    if (
        not force_refresh
        and _local_health_cache is not None
        and now - _local_health_checked_at < _health_cache_ttl_seconds()
    ):
        return bool(_local_health_cache.get("reachable"))
    _local_health_cache = check_mineru_local_health()
    _local_health_checked_at = now
    return bool(_local_health_cache.get("reachable"))


def invalidate_mineru_local_health_cache() -> None:
    global _local_health_cache, _local_health_checked_at
    _local_health_cache = None
    _local_health_checked_at = 0.0


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def mineru_local_enabled() -> bool:
    from data_agent.parsing.mineru_config import mineru_local_enabled as _enabled

    return _enabled()


def mineru_local_supports(file_name: str) -> bool:
    return mineru_local_enabled() and Path(file_name).suffix.lower() in _SUPPORTED_EXTENSIONS


def _base_url() -> str:
    return (
        os.getenv("MINERU_LOCAL_API_BASE")
        or os.getenv("MINERU_API_BASE")
        or _DEFAULT_BASE_URL
    ).rstrip("/")


def _connect_timeout_seconds() -> float:
    raw = os.getenv("MINERU_LOCAL_CONNECT_TIMEOUT_SECONDS", "10")
    try:
        return max(1.0, float(raw))
    except ValueError:
        return 10.0


def _request_timeout_seconds() -> float:
    raw = os.getenv("MINERU_LOCAL_REQUEST_TIMEOUT_SECONDS", "300")
    try:
        return max(1.0, float(raw))
    except ValueError:
        return 300.0


def _request_timeout() -> tuple[float, float]:
    return _connect_timeout_seconds(), _request_timeout_seconds()


def check_mineru_local_health(timeout: float | None = None) -> dict:
    """Probe MinerU local FastAPI service reachability."""
    base = _base_url()
    result = {
        "enabled": mineru_local_enabled(),
        "base_url": base,
        "reachable": False,
        "detail": "",
    }
    if not result["enabled"]:
        result["detail"] = "disabled"
        return result

    probe_timeout = timeout if timeout is not None else _connect_timeout_seconds()
    for path in ("/docs", "/openapi.json", "/"):
        try:
            response = requests.get(f"{base}{path}", timeout=probe_timeout)
            if response.status_code < 500:
                result["reachable"] = True
                result["detail"] = f"HTTP {response.status_code} {path}"
                return result
        except Exception as exc:
            result["detail"] = str(exc)
    return result


def _extract_markdown(payload: dict, file_name: str) -> str:
    results = payload.get("results")
    if isinstance(results, dict):
        stem = Path(file_name).stem
        lookup_keys = [stem, Path(file_name).name]
        for key in lookup_keys:
            entry = results.get(key)
            if isinstance(entry, dict):
                for field in ("md_content", "md", "markdown"):
                    value = entry.get(field)
                    if isinstance(value, str) and value.strip():
                        return value
        for entry in results.values():
            if not isinstance(entry, dict):
                continue
            for field in ("md_content", "md", "markdown"):
                value = entry.get(field)
                if isinstance(value, str) and value.strip():
                    return value

    for field in ("md_content", "md", "markdown"):
        value = payload.get(field)
        if isinstance(value, str) and value.strip():
            return value
    return ""


_VALID_PARSE_METHODS = frozenset({"auto", "ocr", "txt"})
_KNOWN_BACKEND_VALUES = frozenset({"pipeline", "hybrid-auto-engine", "vlm-auto-engine"})


def _looks_like_backend(value: str) -> bool:
    lowered = value.lower()
    return lowered in _KNOWN_BACKEND_VALUES or lowered == "pipeline" or "hybrid" in lowered or "vlm" in lowered


def _resolve_local_form_options(parse_mode: str | None = None) -> tuple[str, str]:
    """Map env/API mode strings to MinerU local ``parse_method`` and ``backend``.

    MinerU local ``/file_parse`` only accepts parse_method in {auto, ocr, txt}.
    Values such as ``hybrid-auto-engine`` belong to ``backend``, not parse_method.
    """
    env_parse = (os.getenv("MINERU_LOCAL_PARSE_METHOD") or "ocr").strip() or "ocr"
    env_backend = (os.getenv("MINERU_LOCAL_BACKEND") or "pipeline").strip() or "pipeline"
    raw = (parse_mode or "").strip() or env_parse

    parse_method = "auto"
    backend = env_backend

    if raw.lower() in _VALID_PARSE_METHODS:
        parse_method = raw.lower()
    elif _looks_like_backend(raw):
        backend = raw
        if env_parse.lower() in _VALID_PARSE_METHODS:
            parse_method = env_parse.lower()
    elif env_parse.lower() in _VALID_PARSE_METHODS:
        parse_method = env_parse.lower()
    elif _looks_like_backend(env_parse):
        backend = env_parse

    return parse_method, backend


def _form_data(parse_mode: str | None = None) -> dict[str, str]:
    parse_method, backend = _resolve_local_form_options(parse_mode)
    return {
        "return_md": "true",
        "return_middle_json": "true",
        "return_model_output": "false",
        "return_content_list": "true",
        "return_images": "false",
        "response_format_zip": "false",
        "lang_list": os.getenv("MINERU_LOCAL_LANG_LIST", "ch"),
        "backend": backend,
        "parse_method": parse_method,
        "formula_enable": os.getenv("MINERU_LOCAL_FORMULA_ENABLE", "true"),
        "table_enable": os.getenv("MINERU_LOCAL_TABLE_ENABLE", "true"),
    }


def _extract_result_entry(payload: dict, file_name: str) -> dict:
    results = payload.get("results")
    if not isinstance(results, dict):
        return payload
    stem = Path(file_name).stem
    for key in (stem, Path(file_name).name):
        entry = results.get(key)
        if isinstance(entry, dict):
            return entry
    for entry in results.values():
        if isinstance(entry, dict):
            return entry
    return payload


def _coerce_json_list(value) -> list:
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except ValueError:
            return []
        return parsed if isinstance(parsed, list) else []
    return []


def _extract_content_list(payload: dict, file_name: str) -> list:
    entry = _extract_result_entry(payload, file_name)
    for field in ("content_list", "content_list_json", "content"):
        items = _coerce_json_list(entry.get(field))
        if items:
            return items
    for field in ("content_list", "content_list_json", "content"):
        items = _coerce_json_list(payload.get(field))
        if items:
            return items
    return []


def _extract_middle_json_presence(payload: dict, file_name: str) -> bool:
    entry = _extract_result_entry(payload, file_name)
    for field in ("middle_json", "middle_info", "middle"):
        if entry.get(field) or payload.get(field):
            return True
    return False


def _block_type(raw_type: str) -> str:
    value = raw_type.lower()
    if "table" in value:
        return "table"
    if "image" in value or "figure" in value:
        return "figure"
    if "title" in value or "heading" in value:
        return "heading"
    if "formula" in value or "equation" in value:
        return "formula"
    return "paragraph"


def _content_part_text(value) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = _content_part_text(item)
                if text:
                    parts.append(text)
        return " ".join(part for part in parts if part).strip()
    if isinstance(value, dict):
        parts: list[str] = []
        for key in ("content", "text", "html"):
            text = _content_part_text(value.get(key))
            if text:
                parts.append(text)
        children = value.get("children")
        if isinstance(children, list):
            text = _content_part_text(children)
            if text:
                parts.append(text)
        return " ".join(part for part in parts if part).strip()
    return ""


def _image_ref_from_item(item: dict) -> str | None:
    content = item.get("content")
    if isinstance(content, dict):
        image_source = content.get("image_source")
        if isinstance(image_source, dict):
            path = str(image_source.get("path") or "").strip()
            if path:
                return path
    for key in ("image_path", "img_path"):
        path = str(item.get(key) or "").strip()
        if path:
            return path
    return None


def _caption_from_item(item: dict) -> str | None:
    for key in ("caption", "image_caption", "table_caption"):
        value = item.get(key)
        text = _content_part_text(value)
        if text:
            return text
    content = item.get("content")
    if isinstance(content, dict):
        for key in ("image_caption", "table_caption", "code_caption", "algorithm_caption"):
            text = _content_part_text(content.get(key))
            if text:
                return text
    return None


def _angle_from_item(item: dict) -> int | None:
    raw = item.get("angle")
    if raw is None:
        return None
    try:
        angle = int(raw) % 360
    except (TypeError, ValueError):
        return None
    return angle if angle in {0, 90, 180, 270} else None


def _blocks_from_content_list(items: list) -> list[ParsedDocumentBlock]:
    blocks: list[ParsedDocumentBlock] = []
    flattened_items: list[tuple[dict, int | None]] = []
    for index, item in enumerate(items):
        if isinstance(item, list):
            for nested in item:
                if isinstance(nested, dict):
                    flattened_items.append((nested, index + 1))
            continue
        if isinstance(item, dict):
            flattened_items.append((item, None))

    def _content_text(item: dict, block_type: str) -> str:
        content = item.get("content")
        if isinstance(content, dict):
            if block_type == "table":
                for key in ("table_body", "table_html", "html"):
                    text = _content_part_text(content.get(key))
                    if text:
                        return text
            for key in (
                "html",
                "text",
                "latex",
                "paragraph_content",
                "title_content",
                "math_content",
                "code_content",
                "list_items",
                "page_header_content",
                "page_number_content",
                "page_footnote_content",
            ):
                value = content.get(key)
                text = _content_part_text(value)
                if text:
                    return text
            image_source = content.get("image_source")
            if isinstance(image_source, dict):
                path = str(image_source.get("path") or "").strip()
                if path:
                    return path
        return str(
            item.get("text")
            or item.get("html")
            or item.get("latex")
            or item.get("table_body")
            or item.get("table_html")
            or item.get("image_path")
            or item.get("img_path")
            or (item.get("content") if not isinstance(item.get("content"), dict) else "")
            or ""
        ).strip()

    def _page_hint(item: dict, page_from_nested: int | None) -> int | None:
        for key in ("page_idx", "page", "page_no"):
            if key not in item:
                continue
            try:
                page = int(item.get(key))
            except (TypeError, ValueError):
                continue
            if key == "page_idx":
                return page + 1
            return max(page, 1)
        if page_from_nested is not None:
            return page_from_nested
        return None

    for item, page_from_nested in flattened_items:
        if not isinstance(item, dict):
            continue
        raw_type = str(item.get("type") or item.get("category") or item.get("block_type") or "")
        block_type = _block_type(raw_type)
        text = _content_text(item, block_type)
        if block_type == "table" and not text:
            text = str(item.get("table_body") or item.get("table_html") or item.get("md") or "").strip()
        if not text:
            text = (_caption_from_item(item) or "").strip()
        image_ref = _image_ref_from_item(item)
        bbox = item.get("bbox") or item.get("poly")
        if not isinstance(bbox, list):
            bbox = None
        if not text:
            if block_type == "figure" and (bbox or image_ref):
                text = "[figure]"
            else:
                continue
        from data_agent.parsing.figure_text import looks_like_image_ref

        if block_type not in {"table", "heading", "formula"} and (
            looks_like_image_ref(text) or (image_ref and block_type != "table")
        ):
            if not image_ref and looks_like_image_ref(text):
                image_ref = text
            block_type = "figure"
            text = "[figure]"
        confidence = item.get("score") or item.get("confidence")
        try:
            confidence = float(confidence) if confidence is not None else None
        except (TypeError, ValueError):
            confidence = None
        block = ParsedDocumentBlock(
            block_id=str(uuid.uuid4()),
            block_type=block_type,
            text=text,
            order_index=len(blocks),
            page_hint=_page_hint(item, page_from_nested),
            bbox=bbox,
            angle=_angle_from_item(item),
            confidence=confidence,
            table_markdown=text if block_type == "table" and "|" in text else None,
            formula_latex=text if block_type == "formula" else None,
            caption=_caption_from_item(item),
            image_ref=image_ref,
        )
        blocks.append(block)
    return blocks


def _response_error(payload: dict | None, response: requests.Response) -> str:
    if isinstance(payload, dict):
        for key in ("error", "message", "detail"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value
    text = (response.text or "").strip()
    return text[:500] if text else f"HTTP {response.status_code}"


def parse_via_mineru_local_http(
    file_path: str,
    file_name: str,
    parsed_doc: ParsedDocument,
    *,
    parse_mode: str | None = None,
) -> None:
    parsed_doc.parser_name = "mineru-local"
    if not mineru_local_supports(file_name):
        parsed_doc.parse_status = "failed"
        parsed_doc.warnings.append(
            f"MinerU 本地服务仅支持 PDF/图片，收到 {Path(file_name).suffix.lower()}"
        )
        return
    if not mineru_local_reachable():
        parsed_doc.parse_status = "failed"
        parsed_doc.warnings.append("MinerU 本地服务不可达，已跳过本地解析。")
        return

    try:
        with open(file_path, "rb") as handle:
            response = requests.post(
                f"{_base_url()}/file_parse",
                files={"files": (Path(file_name).name, handle, "application/octet-stream")},
                data=_form_data(parse_mode),
                timeout=_request_timeout(),
            )
        payload: dict | list | None
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        if not isinstance(payload, dict):
            raise RuntimeError(f"MinerU local service returned invalid JSON: {payload!r}")
        if response.status_code >= 400 or payload.get("status") == "failed":
            raise RuntimeError(_response_error(payload, response))

        content_list = _extract_content_list(payload, file_name)
        content_blocks = _blocks_from_content_list(content_list)
        markdown = normalize_mineru_markdown(_extract_markdown(payload, file_name))
        parsed_doc.blocks = content_blocks or markdown_to_parsed_blocks(markdown)
        parsed_doc.parse_status = "ok" if parsed_doc.blocks else "degraded"
        parsed_doc.enhancement_log.append(
            {
                "kind": "mineru_local_payload",
                "parse_mode": (parse_mode or "").strip(),
                "has_content_list": bool(content_list),
                "has_middle_json": _extract_middle_json_presence(payload, file_name),
                "block_source": "content_list" if content_blocks else "markdown",
            }
        )
        backend = payload.get("backend")
        version = payload.get("version")
        if backend or version:
            parsed_doc.warnings.append(
                f"MinerU local backend={backend or 'unknown'} version={version or 'unknown'}"
            )
        if not parsed_doc.blocks:
            parsed_doc.warnings.append("MinerU 本地服务返回空 Markdown。")
    except Exception as exc:
        parsed_doc.parse_status = "failed"
        parsed_doc.warnings.append(f"MinerU 本地服务解析失败: {exc}")
        invalidate_mineru_local_health_cache()


__all__ = [
    "check_mineru_local_health",
    "invalidate_mineru_local_health_cache",
    "mineru_local_enabled",
    "mineru_local_reachable",
    "mineru_local_supports",
    "parse_via_mineru_local_http",
]
