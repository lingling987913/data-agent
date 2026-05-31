"""MinerU v4 precise extract API adapter (batch file upload + zip result).

Uses ``POST /api/v4/file-urls/batch`` for local files when a Token is configured.
Falls back from Agent lightweight API on size/page-limit errors or large files.
"""

from __future__ import annotations

import io
import json
import logging
import os
import time
import uuid
import zipfile
from pathlib import Path
from typing import Any

import requests

from data_agent.parsing.parsers.mineru_agent_parser import (
    assess_markdown_completeness,
    markdown_to_parsed_blocks,
    normalize_mineru_markdown,
)
from data_agent.parsing.parsers.mineru_local_http_parser import _blocks_from_content_list
from data_agent.parsing.schemas import ParsedDocument

logger = logging.getLogger(__name__)

_DEFAULT_BASE_URL = "https://mineru.net/api/v4"
_AGENT_MAX_BYTES = 10 * 1024 * 1024  # 10 MB — Agent lightweight limit

_SUPPORTED_EXTENSIONS = {
    ".pdf",
    ".png",
    ".jpg",
    ".jpeg",
    ".jp2",
    ".webp",
    ".gif",
    ".bmp",
    ".doc",
    ".docx",
    ".ppt",
    ".pptx",
    ".xls",
    ".xlsx",
    ".html",
}
_EXTRACT_ONLY_EXTENSIONS = {".doc", ".ppt", ".xls", ".html"}
_AGENT_LIMIT_ERR_CODES = {-30001, -30003}


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _token() -> str:
    from data_agent.parsing.mineru_config import mineru_token

    return mineru_token()


def mineru_extract_available() -> bool:
    from data_agent.parsing.mineru_config import mineru_extract_available as _available

    return _available()


def mineru_extract_enabled() -> bool:
    """True when v4 extract may be chosen as the primary parser."""
    from data_agent.parsing.mineru_config import mineru_extract_enabled as _enabled

    return _enabled()


def mineru_extract_supports(file_name: str) -> bool:
    return Path(file_name).suffix.lower() in _SUPPORTED_EXTENSIONS


def should_prefer_mineru_extract(file_path: str, file_name: str) -> bool:
    """True when v4 extract should run instead of Agent lightweight API."""
    if not mineru_extract_enabled() or not mineru_extract_supports(file_name):
        return False
    mode = os.getenv("MINERU_API_MODE", "").strip().lower()
    if mode in {"extract", "v4", "precise", "standard"}:
        return True
    ext = Path(file_name).suffix.lower()
    if ext in _EXTRACT_ONLY_EXTENSIONS:
        return True
    try:
        if os.path.getsize(file_path) > _AGENT_MAX_BYTES:
            return True
    except OSError:
        pass
    return False


def agent_failure_should_retry_extract(err_msg: str, err_code: Any) -> bool:
    if not mineru_extract_available():
        return False
    try:
        code = int(err_code)
    except (TypeError, ValueError):
        code = None
    if code in _AGENT_LIMIT_ERR_CODES:
        return True
    lowered = (err_msg or "").lower()
    return any(
        phrase in lowered
        for phrase in (
            "exceeds lightweight api limit",
            "file size exceeds",
            "page count exceeds",
            "请使用标准 api",
        )
    )


def _base_url() -> str:
    return (
        os.getenv("MINERU_EXTRACT_API_BASE")
        or os.getenv("MINERU_AGENT_API_BASE", "").replace("/api/v1/agent", "/api/v4")
        or _DEFAULT_BASE_URL
    ).rstrip("/")


def _headers() -> dict[str, str]:
    token = _token()
    if not token:
        raise RuntimeError("MinerU extract API requires MINERU_AGENT_API_TOKEN")
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }


def _request_timeout() -> float:
    return float(os.getenv("MINERU_EXTRACT_REQUEST_TIMEOUT_SECONDS", "60"))


def _upload_timeout() -> float:
    return float(os.getenv("MINERU_EXTRACT_UPLOAD_TIMEOUT_SECONDS", "300"))


def _poll_timeout() -> float:
    return float(os.getenv("MINERU_EXTRACT_POLL_TIMEOUT_SECONDS", "600"))


def _poll_interval() -> float:
    return float(os.getenv("MINERU_EXTRACT_POLL_INTERVAL_SECONDS", "5"))


def _model_version(file_name: str) -> str:
    ext = Path(file_name).suffix.lower()
    if ext == ".html":
        return os.getenv("MINERU_EXTRACT_MODEL_VERSION_HTML", "MinerU-HTML")
    return os.getenv("MINERU_EXTRACT_MODEL_VERSION", "vlm")


def _batch_payload(file_name: str) -> dict[str, Any]:
    ext = Path(file_name).suffix.lower()
    default_ocr = ext == ".pdf"
    file_entry: dict[str, Any] = {
        "name": Path(file_name).name,
        "data_id": str(uuid.uuid4())[:32],
        "is_ocr": _env_bool("MINERU_EXTRACT_IS_OCR", _env_bool("MINERU_AGENT_IS_OCR", default_ocr)),
    }
    page_ranges = (
        os.getenv("MINERU_EXTRACT_PAGE_RANGES", "").strip()
        or os.getenv("MINERU_AGENT_PAGE_RANGE", "").strip()
    )
    if page_ranges:
        file_entry["page_ranges"] = page_ranges

    payload: dict[str, Any] = {
        "files": [file_entry],
        "model_version": _model_version(file_name),
        "enable_formula": _env_bool(
            "MINERU_EXTRACT_ENABLE_FORMULA",
            _env_bool("MINERU_AGENT_ENABLE_FORMULA", True),
        ),
        "enable_table": _env_bool(
            "MINERU_EXTRACT_ENABLE_TABLE",
            _env_bool("MINERU_AGENT_ENABLE_TABLE", True),
        ),
        "language": os.getenv("MINERU_EXTRACT_LANGUAGE", os.getenv("MINERU_AGENT_LANGUAGE", "ch")),
    }
    extra_formats = os.getenv("MINERU_EXTRACT_EXTRA_FORMATS", "").strip()
    if extra_formats:
        payload["extra_formats"] = [part.strip() for part in extra_formats.split(",") if part.strip()]
    return payload


def _require_success(payload: dict[str, Any], operation: str) -> dict[str, Any]:
    if int(payload.get("code", -1)) != 0:
        raise RuntimeError(f"MinerU extract {operation} failed: {payload.get('msg') or payload}")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise RuntimeError(f"MinerU extract {operation} returned invalid data: {payload}")
    return data


def _request_with_retry(method: str, url: str, **kwargs) -> requests.Response:
    max_retries = int(os.getenv("MINERU_EXTRACT_MAX_RETRIES", "3"))
    backoff = float(os.getenv("MINERU_EXTRACT_RETRY_BACKOFF_SECONDS", "2"))
    last_response: requests.Response | None = None
    for attempt in range(max_retries + 1):
        response = requests.request(method, url, **kwargs)
        last_response = response
        if response.status_code != 429 or attempt >= max_retries:
            response.raise_for_status()
            return response
        retry_after = response.headers.get("Retry-After")
        sleep_s = float(retry_after) if retry_after and retry_after.isdigit() else backoff * (attempt + 1)
        logger.warning("[MinerU extract] HTTP 429, retry %s/%s after %.1fs", attempt + 1, max_retries, sleep_s)
        time.sleep(sleep_s)
    assert last_response is not None
    last_response.raise_for_status()
    return last_response


def _submit_batch_upload(file_path: str, file_name: str) -> str:
    response = _request_with_retry(
        "POST",
        f"{_base_url()}/file-urls/batch",
        json=_batch_payload(file_name),
        headers=_headers(),
        timeout=_request_timeout(),
    )
    data = _require_success(response.json(), "create batch upload")
    upload_urls = data.get("file_urls") or []
    batch_id = str(data.get("batch_id") or "")
    if not batch_id or not upload_urls:
        raise RuntimeError("MinerU extract batch response missing batch_id or file_urls")

    with open(file_path, "rb") as handle:
        upload = _request_with_retry(
            "PUT",
            str(upload_urls[0]),
            data=handle,
            timeout=_upload_timeout(),
        )
    if upload.status_code not in {200, 201, 204}:
        raise RuntimeError(f"MinerU extract file upload failed: HTTP {upload.status_code}")
    return batch_id


def _poll_batch_result(batch_id: str, file_name: str) -> str:
    deadline = time.time() + _poll_timeout()
    interval = _poll_interval()
    target_name = Path(file_name).name
    last_state = ""
    while time.time() < deadline:
        response = _request_with_retry(
            "GET",
            f"{_base_url()}/extract-results/batch/{batch_id}",
            headers=_headers(),
            timeout=_request_timeout(),
        )
        data = _require_success(response.json(), "poll batch result")
        results = data.get("extract_result") or []
        if not isinstance(results, list):
            raise RuntimeError(f"MinerU extract batch result invalid: {data}")

        entry = None
        for item in results:
            if isinstance(item, dict) and str(item.get("file_name") or "") == target_name:
                entry = item
                break
        if entry is None and len(results) == 1 and isinstance(results[0], dict):
            entry = results[0]

        if not isinstance(entry, dict):
            time.sleep(interval)
            continue

        state = str(entry.get("state") or "")
        last_state = state
        if state == "done":
            zip_url = str(entry.get("full_zip_url") or "")
            if not zip_url:
                raise RuntimeError("MinerU extract done but full_zip_url missing")
            return zip_url
        if state == "failed":
            raise RuntimeError(
                f"MinerU extract parse failed: {entry.get('err_msg') or entry.get('err_code') or entry}"
            )
        time.sleep(interval)
    raise TimeoutError(
        f"MinerU extract poll timed out after {_poll_timeout():.0f}s; last_state={last_state}"
    )


def _download_zip(zip_url: str) -> bytes:
    response = _request_with_retry(
        "GET",
        zip_url,
        timeout=float(os.getenv("MINERU_EXTRACT_DOWNLOAD_TIMEOUT_SECONDS", "120")),
    )
    return response.content


def _read_zip_markdown(zip_bytes: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
        names = archive.namelist()
        for name in names:
            if name.endswith("full.md"):
                return archive.read(name).decode("utf-8")
        for name in names:
            if name.lower().endswith(".md") and "full" in name.lower():
                return archive.read(name).decode("utf-8")
        for name in names:
            if name.lower().endswith(".md"):
                return archive.read(name).decode("utf-8")
    return ""


def _iter_zip_content_list_payloads(zip_bytes: bytes):
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
        names = archive.namelist()
        ordered_names = sorted(
            names,
            key=lambda name: (
                0
                if "content_list_v2" in name.lower()
                else 1
                if name.lower().endswith("content_list.json")
                else 2
                if "content_list" in name.lower()
                else 3,
                name,
            ),
        )
        for name in ordered_names:
            lower = name.lower()
            if "content_list" in lower and lower.endswith(".json"):
                try:
                    payload = json.loads(archive.read(name).decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue
                if isinstance(payload, list):
                    yield name, payload


def _read_zip_content_list(zip_bytes: bytes) -> list:
    for _, payload in _iter_zip_content_list_payloads(zip_bytes):
        return payload
    return []


def _select_zip_content_blocks(zip_bytes: bytes) -> tuple[list, str, list]:
    """Pick the first content_list JSON that yields layout blocks (v2 then v1)."""
    fallback_name = ""
    fallback_payload: list = []
    for name, payload in _iter_zip_content_list_payloads(zip_bytes):
        blocks = _blocks_from_content_list(payload)
        if blocks:
            return payload, name, blocks
        if not fallback_payload:
            fallback_name, fallback_payload = name, payload
    return fallback_payload, fallback_name, []


def _content_block_page_stats(blocks: list) -> dict[str, int]:
    page_numbers = sorted({int(block.page_hint or 1) for block in blocks})
    return {
        "page_count": len(page_numbers),
        "page_hint_max": page_numbers[-1] if page_numbers else 0,
    }


def _extract_task_payload(url: str, file_name: str) -> dict[str, Any]:
    ext = Path(file_name).suffix.lower()
    default_ocr = ext == ".pdf"
    payload: dict[str, Any] = {
        "url": url,
        "model_version": _model_version(file_name),
        "is_ocr": _env_bool("MINERU_EXTRACT_IS_OCR", _env_bool("MINERU_AGENT_IS_OCR", default_ocr)),
        "enable_formula": _env_bool(
            "MINERU_EXTRACT_ENABLE_FORMULA",
            _env_bool("MINERU_AGENT_ENABLE_FORMULA", True),
        ),
        "enable_table": _env_bool(
            "MINERU_EXTRACT_ENABLE_TABLE",
            _env_bool("MINERU_AGENT_ENABLE_TABLE", True),
        ),
        "language": os.getenv("MINERU_EXTRACT_LANGUAGE", os.getenv("MINERU_AGENT_LANGUAGE", "ch")),
    }
    page_ranges = (
        os.getenv("MINERU_EXTRACT_PAGE_RANGES", "").strip()
        or os.getenv("MINERU_AGENT_PAGE_RANGE", "").strip()
    )
    if page_ranges:
        payload["page_ranges"] = page_ranges
    extra_formats = os.getenv("MINERU_EXTRACT_EXTRA_FORMATS", "").strip()
    if extra_formats:
        payload["extra_formats"] = [part.strip() for part in extra_formats.split(",") if part.strip()]
    return payload


def _submit_url_task(url: str, file_name: str) -> str:
    response = _request_with_retry(
        "POST",
        f"{_base_url()}/extract/task",
        json=_extract_task_payload(url, file_name),
        headers=_headers(),
        timeout=_request_timeout(),
    )
    data = _require_success(response.json(), "create URL task")
    task_id = str(data.get("task_id") or "")
    if not task_id:
        raise RuntimeError("MinerU extract URL task response missing task_id")
    return task_id


def _poll_task_result(task_id: str) -> str:
    deadline = time.time() + _poll_timeout()
    interval = _poll_interval()
    last_state = ""
    while time.time() < deadline:
        response = _request_with_retry(
            "GET",
            f"{_base_url()}/extract/task/{task_id}",
            headers=_headers(),
            timeout=_request_timeout(),
        )
        data = _require_success(response.json(), "poll task result")
        state = str(data.get("state") or "")
        last_state = state
        if state == "done":
            zip_url = str(data.get("full_zip_url") or "")
            if not zip_url:
                raise RuntimeError("MinerU extract done but full_zip_url missing")
            return zip_url
        if state == "failed":
            raise RuntimeError(
                f"MinerU extract parse failed: {data.get('err_msg') or data.get('err_code') or data}"
            )
        time.sleep(interval)
    raise TimeoutError(
        f"MinerU extract poll timed out after {_poll_timeout():.0f}s; last_state={last_state}"
    )


def _apply_zip_bytes(
    file_path: str,
    parsed_doc: ParsedDocument,
    zip_bytes: bytes,
    *,
    batch_id: str | None = None,
    task_id: str | None = None,
    zip_url: str = "",
) -> None:
    raw_markdown = _read_zip_markdown(zip_bytes)
    content_list, content_list_name, content_blocks = _select_zip_content_blocks(zip_bytes)
    block_source = "content_list" if content_blocks else "markdown"
    if content_blocks and "content_list_v2" not in content_list_name.lower():
        logger.info(
            "[MinerU extract] using legacy content_list %s (%s blocks)",
            content_list_name,
            len(content_blocks),
        )
    complete, incompleteness_msg = assess_markdown_completeness(file_path, raw_markdown)
    if not complete:
        logger.warning("[MinerU extract] %s", incompleteness_msg)
        parsed_doc.warnings.append(incompleteness_msg)
    markdown = normalize_mineru_markdown(raw_markdown)
    parsed_doc.blocks = content_blocks or markdown_to_parsed_blocks(markdown)
    page_stats = _content_block_page_stats(parsed_doc.blocks)
    if block_source == "markdown" and content_list_name:
        logger.warning(
            "[MinerU extract] content_list %s produced 0 blocks; fell back to markdown "
            "(%s blocks, %s pages)",
            content_list_name,
            len(parsed_doc.blocks),
            page_stats["page_count"],
        )
    parsed_doc.enhancement_log.append(
        {
            "kind": "mineru_extract_payload",
            "batch_id": batch_id,
            "task_id": task_id,
            "has_content_list": bool(content_list),
            "content_list_file": content_list_name,
            "block_source": block_source,
            "zip_url": zip_url,
            **page_stats,
        }
    )
    if not parsed_doc.blocks:
        parsed_doc.parse_status = "degraded"
        parsed_doc.warnings.append("MinerU extract returned empty content.")
    elif not complete:
        parsed_doc.parse_status = "degraded"
    else:
        parsed_doc.parse_status = "ok"


def parse_via_mineru_extract(file_path: str, file_name: str, parsed_doc: ParsedDocument) -> None:
    parsed_doc.parser_name = "mineru-extract"
    if not mineru_extract_supports(file_name):
        parsed_doc.parse_status = "failed"
        parsed_doc.warnings.append(
            f"MinerU extract API does not support {Path(file_name).suffix.lower()}"
        )
        return
    if not mineru_extract_available():
        parsed_doc.parse_status = "failed"
        parsed_doc.warnings.append("MinerU extract API 未启用（需配置 MINERU_AGENT_API_TOKEN）")
        return

    try:
        batch_id = _submit_batch_upload(file_path, file_name)
        zip_url = _poll_batch_result(batch_id, file_name)
        _apply_zip_bytes(
            file_path,
            parsed_doc,
            _download_zip(zip_url),
            batch_id=batch_id,
            zip_url=zip_url,
        )
    except Exception as exc:
        parsed_doc.parse_status = "failed"
        parsed_doc.warnings.append(f"MinerU extract parse error: {exc}")


def parse_via_mineru_extract_url(url: str, file_name: str, parsed_doc: ParsedDocument) -> None:
    parsed_doc.parser_name = "mineru-extract"
    if not mineru_extract_supports(file_name):
        parsed_doc.parse_status = "failed"
        parsed_doc.warnings.append(
            f"MinerU extract API does not support {Path(file_name).suffix.lower()}"
        )
        return
    if not mineru_extract_available():
        parsed_doc.parse_status = "failed"
        parsed_doc.warnings.append("MinerU extract API 未启用（需配置 MINERU_AGENT_API_TOKEN）")
        return

    try:
        task_id = _submit_url_task(url, file_name)
        zip_url = _poll_task_result(task_id)
        _apply_zip_bytes(
            url,
            parsed_doc,
            _download_zip(zip_url),
            task_id=task_id,
            zip_url=zip_url,
        )
    except Exception as exc:
        parsed_doc.parse_status = "failed"
        parsed_doc.warnings.append(f"MinerU extract URL parse error: {exc}")


__all__ = [
    "agent_failure_should_retry_extract",
    "mineru_extract_available",
    "mineru_extract_enabled",
    "mineru_extract_supports",
    "parse_via_mineru_extract",
    "parse_via_mineru_extract_url",
    "should_prefer_mineru_extract",
]
