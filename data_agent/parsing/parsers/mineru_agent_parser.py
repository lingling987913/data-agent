"""MinerU Agent lightweight API adapter.

The Agent API returns Markdown only. This adapter turns that Markdown into the
same ParsedDocument/ParsedDocumentBlock shape used by the rest of Aqua, and
normalizes HTML tables / encoded formulas before the content reaches review
LLMs.
"""

from __future__ import annotations

import html
import logging
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import requests

from data_agent.parsing.schemas import ParsedDocument, ParsedDocumentBlock

logger = logging.getLogger(__name__)


class MinerUAgentError(RuntimeError):
    """Raised when MinerU Agent task enters failed state."""

    def __init__(self, message: str, err_code: Any = None):
        super().__init__(message)
        self.err_code = err_code


# Agent lightweight API file types (see mineru.net/apiManage/docs).
_AGENT_SUPPORTED_EXTENSIONS = {
    ".pdf", ".png", ".jpg", ".jpeg", ".jp2", ".webp", ".gif", ".bmp",
    ".docx", ".pptx", ".xlsx",
}
# Legacy alias kept for callers that expect the broader set name.
_SUPPORTED_EXTENSIONS = _AGENT_SUPPORTED_EXTENSIONS
_DEFAULT_BASE_URL = "https://mineru.net/api/v1/agent"
_TABLE_RE = re.compile(r"<table\b[^>]*>.*?</table>", re.IGNORECASE | re.DOTALL)
_TR_RE = re.compile(r"<tr\b[^>]*>.*?</tr>", re.IGNORECASE | re.DOTALL)
_CELL_RE = re.compile(r"<t[dh]\b[^>]*>(.*?)</t[dh]>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$")
_IMAGE_MD_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
# 大于 100KB 的 PDF 若 markdown 字符数过低，视为内容不完整
_INCOMPLETE_RATIO = float(os.getenv("MINERU_AGENT_INCOMPLETE_RATIO", "300"))


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def mineru_agent_enabled() -> bool:
    from data_agent.parsing.mineru_config import mineru_agent_enabled as _enabled

    return _enabled()


def mineru_agent_supports(file_name: str) -> bool:
    return Path(file_name).suffix.lower() in _SUPPORTED_EXTENSIONS


def _base_url() -> str:
    return (
        os.getenv("MINERU_AGENT_API_BASE")
        or os.getenv("MINERU_API_BASE")
        or _DEFAULT_BASE_URL
    ).rstrip("/")


def _headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    token = os.getenv("MINERU_AGENT_API_TOKEN") or os.getenv("MINERU_API_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _request_payload(file_name: str, parse_mode: str | None = None) -> dict[str, Any]:
    ext = Path(file_name).suffix.lower()
    # 复杂/扫描 PDF 默认开启 OCR，可通过 MINERU_AGENT_IS_OCR 覆盖
    default_ocr = ext == ".pdf"
    payload: dict[str, Any] = {
        "file_name": file_name,
        "language": os.getenv("MINERU_AGENT_LANGUAGE", "ch"),
        "enable_table": _env_bool("MINERU_AGENT_ENABLE_TABLE", True),
        "enable_formula": _env_bool("MINERU_AGENT_ENABLE_FORMULA", True),
        "is_ocr": _env_bool("MINERU_AGENT_IS_OCR", default_ocr),
    }
    mode = (parse_mode or os.getenv("MINERU_AGENT_PARSE_MODE", "")).strip()
    if mode:
        payload["mode"] = mode
    page_range = os.getenv("MINERU_AGENT_PAGE_RANGE", "").strip()
    if page_range:
        payload["page_range"] = page_range
    return payload


def _is_url(value: str) -> bool:
    return value.lower().startswith(("http://", "https://"))


def _request_with_retry(method: str, url: str, **kwargs) -> requests.Response:
    max_retries = int(os.getenv("MINERU_AGENT_MAX_RETRIES", "3"))
    backoff = float(os.getenv("MINERU_AGENT_RETRY_BACKOFF_SECONDS", "2"))
    last_response: requests.Response | None = None
    for attempt in range(max_retries + 1):
        response = requests.request(method, url, **kwargs)
        last_response = response
        if response.status_code != 429 or attempt >= max_retries:
            response.raise_for_status()
            return response
        retry_after = response.headers.get("Retry-After")
        sleep_s = float(retry_after) if retry_after and retry_after.isdigit() else backoff * (attempt + 1)
        logger.warning("[MinerU Agent] HTTP 429, retry %s/%s after %.1fs", attempt + 1, max_retries, sleep_s)
        time.sleep(sleep_s)
    assert last_response is not None
    last_response.raise_for_status()
    return last_response


def _require_success(payload: dict[str, Any], operation: str) -> dict[str, Any]:
    if int(payload.get("code", -1)) != 0:
        raise RuntimeError(f"MinerU Agent {operation} failed: {payload.get('msg') or payload}")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise RuntimeError(f"MinerU Agent {operation} returned invalid data: {payload}")
    return data


def _submit_file_task(file_path: str, file_name: str, parse_mode: str | None = None) -> str:
    response = _request_with_retry(
        "POST",
        f"{_base_url()}/parse/file",
        json=_request_payload(file_name, parse_mode=parse_mode),
        headers=_headers(),
        timeout=float(os.getenv("MINERU_AGENT_REQUEST_TIMEOUT_SECONDS", "30")),
    )
    data = _require_success(response.json(), "create file task")
    task_id = str(data.get("task_id") or "")
    upload_url = str(data.get("file_url") or "")
    if not task_id or not upload_url:
        raise RuntimeError("MinerU Agent file task response missing task_id or file_url")

    with open(file_path, "rb") as f:
        upload = _request_with_retry(
            "PUT",
            upload_url,
            data=f,
            timeout=float(os.getenv("MINERU_AGENT_UPLOAD_TIMEOUT_SECONDS", "120")),
        )
    if upload.status_code not in {200, 201, 204}:
        raise RuntimeError(f"MinerU Agent signed upload failed: HTTP {upload.status_code}")
    return task_id


def _submit_url_task(url: str, file_name: str, parse_mode: str | None = None) -> str:
    payload = _request_payload(file_name, parse_mode=parse_mode)
    payload["url"] = url
    response = _request_with_retry(
        "POST",
        f"{_base_url()}/parse/url",
        json=payload,
        headers=_headers(),
        timeout=float(os.getenv("MINERU_AGENT_REQUEST_TIMEOUT_SECONDS", "30")),
    )
    data = _require_success(response.json(), "create URL task")
    task_id = str(data.get("task_id") or "")
    if not task_id:
        raise RuntimeError("MinerU Agent URL task response missing task_id")
    return task_id


def _poll_markdown(task_id: str) -> tuple[str, str]:
    """轮询任务直至完成，返回 (markdown 正文, markdown CDN URL)。"""
    timeout = float(os.getenv("MINERU_AGENT_POLL_TIMEOUT_SECONDS", "300"))
    interval = float(os.getenv("MINERU_AGENT_POLL_INTERVAL_SECONDS", "3"))
    deadline = time.time() + timeout
    last_state = ""
    while time.time() < deadline:
        response = _request_with_retry(
            "GET",
            f"{_base_url()}/parse/{task_id}",
            headers=_headers(),
            timeout=float(os.getenv("MINERU_AGENT_REQUEST_TIMEOUT_SECONDS", "30")),
        )
        data = _require_success(response.json(), "poll task")
        state = str(data.get("state") or "")
        last_state = state
        if state == "done":
            markdown_url = str(data.get("markdown_url") or "")
            if not markdown_url:
                raise RuntimeError("MinerU Agent task done but markdown_url missing")
            md_response = _request_with_retry(
                "GET",
                markdown_url,
                timeout=float(os.getenv("MINERU_AGENT_DOWNLOAD_TIMEOUT_SECONDS", "60")),
            )
            md_response.encoding = md_response.encoding or "utf-8"
            return md_response.text, markdown_url
        if state == "failed":
            raise MinerUAgentError(
                str(data.get("err_msg") or data.get("err_code") or data),
                err_code=data.get("err_code"),
            )
        time.sleep(interval)
    raise TimeoutError(f"MinerU Agent parse timed out after {timeout:.0f}s; last_state={last_state}")


def _resolve_image_urls(markdown_url: str, markdown: str) -> dict[str, str]:
    """把相对路径图片引用解析为完整 CDN URL。"""
    base = markdown_url.rsplit("/", 1)[0]
    images: dict[str, str] = {}
    for match in _IMAGE_MD_RE.finditer(markdown):
        src = match.group(2).strip()
        if src and not src.startswith("http"):
            images[src] = f"{base}/{src.lstrip('/')}"
    return images


def _image_ocr_from_markdown(markdown: str) -> dict[str, str]:
    """从 Markdown 图片 alt 文本提取 MinerU OCR 结果（is_ocr=True 时 alt 常含识别文字）。"""
    ocr: dict[str, str] = {}
    for match in _IMAGE_MD_RE.finditer(markdown):
        alt, src = match.group(1).strip(), match.group(2).strip()
        if alt and len(alt) > 2 and not alt.lower().startswith("image"):
            ocr[src] = alt
    return ocr


def _download_image(url: str) -> bytes | None:
    """下载 MinerU CDN 图片，失败时返回 None（不阻断主流程）。"""
    try:
        response = requests.get(
            url,
            timeout=float(os.getenv("MINERU_AGENT_IMAGE_DOWNLOAD_TIMEOUT_SECONDS", "15")),
        )
        response.raise_for_status()
        return response.content
    except Exception as exc:
        logger.warning("[MinerU Agent] image download failed %s: %s", url, exc)
        return None


def _build_image_ocr_map(
    markdown: str,
    image_urls: dict[str, str],
    *,
    download_images: bool = True,
) -> dict[str, str]:
    """合并 Markdown alt OCR 与可选的图片下载校验。"""
    ocr_map = _image_ocr_from_markdown(markdown)
    if not download_images:
        return ocr_map
    for rel_path, full_url in image_urls.items():
        if _download_image(full_url) is None:
            continue
        # 下载成功即确认 URL 可用；OCR 文本仍以 MinerU markdown alt 为准
        if rel_path not in ocr_map:
            logger.debug("[MinerU Agent] image downloaded without OCR alt: %s", rel_path)
    return ocr_map


def _strip_tags(value: str) -> str:
    text = _TAG_RE.sub("", value)
    text = html.unescape(unquote(text))
    return re.sub(r"\s+", " ", text).strip()


def _html_table_to_markdown(match: re.Match[str]) -> str:
    table = match.group(0)
    rows: list[list[str]] = []
    for row_match in _TR_RE.finditer(table):
        cells = [_strip_tags(cell.group(1)) for cell in _CELL_RE.finditer(row_match.group(0))]
        if cells:
            rows.append(cells)
    if not rows:
        return _strip_tags(table)

    width = max(len(row) for row in rows)
    normalized = [row + [""] * (width - len(row)) for row in rows]
    lines = ["| " + " | ".join(normalized[0]) + " |"]
    lines.append("| " + " | ".join(["---"] * width) + " |")
    for row in normalized[1:]:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def normalize_mineru_markdown(markdown: str) -> str:
    """Normalize MinerU Markdown before it is sent into LLM review.

    LLMs can often read raw HTML tables and encoded formulas, but审查场景 needs
    auditable evidence. We normalize tables to Markdown rows and decode entities
    so evidence snippets are stable and readable.
    """
    text = html.unescape(unquote(markdown or ""))
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = _TABLE_RE.sub(_html_table_to_markdown, text)
    text = re.sub(r"</?(tbody|thead|tfoot)\b[^>]*>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"<(span|div|p)\b[^>]*>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"</(span|div|p)>", "\n", text, flags=re.IGNORECASE)
    text = _TAG_RE.sub("", text)
    text = html.unescape(unquote(text))
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def assess_markdown_completeness(file_path: str, markdown: str) -> tuple[bool, str]:
    """检测 MinerU 返回的 markdown 是否明显不完整。"""
    try:
        file_size = os.path.getsize(file_path)
    except OSError:
        return True, ""

    char_count = len((markdown or "").strip())
    suffix = Path(file_path).suffix.lower()
    if suffix != ".pdf" or file_size < 100_000:
        return True, ""

    expected_min = max(2000, int(file_size / _INCOMPLETE_RATIO))
    if char_count < expected_min:
        msg = (
            f"MinerU markdown likely incomplete: {char_count} chars from "
            f"{file_size} byte PDF (expected >= {expected_min})"
        )
        return False, msg
    return True, ""


def markdown_to_parsed_blocks(
    markdown: str,
    *,
    image_urls: dict[str, str] | None = None,
    image_ocr: dict[str, str] | None = None,
) -> list[ParsedDocumentBlock]:
    """Convert MinerU Markdown into structured ParsedDocumentBlock entries."""
    return _markdown_blocks(markdown, "", image_urls=image_urls, image_ocr=image_ocr)


def _markdown_blocks(
    markdown: str,
    file_name: str,
    *,
    image_urls: dict[str, str] | None = None,
    image_ocr: dict[str, str] | None = None,
) -> list[ParsedDocumentBlock]:
    blocks: list[ParsedDocumentBlock] = []
    pending: list[str] = []

    def flush_paragraph() -> None:
        text = "\n".join(line for line in pending if line.strip()).strip()
        pending.clear()
        if not text:
            return
        block_type = "table" if text.startswith("|") and "\n|" in text else "paragraph"
        blocks.append(ParsedDocumentBlock(
            block_id=str(uuid.uuid4()),
            block_type=block_type,
            text=text,
            order_index=len(blocks),
        ))

    for raw_line in markdown.splitlines():
        line = raw_line.rstrip()
        image_match = _IMAGE_MD_RE.match(line.strip())
        if image_match:
            flush_paragraph()
            alt, src = image_match.group(1).strip(), image_match.group(2).strip()
            full_src = (image_urls or {}).get(src, src)
            ocr_text = (image_ocr or {}).get(src, "")
            display_alt = alt or ocr_text
            figure_text = f"![{display_alt}]({full_src})"
            caption = ocr_text or (alt if alt else None)
            blocks.append(ParsedDocumentBlock(
                block_id=str(uuid.uuid4()),
                block_type="figure",
                text=figure_text,
                caption=caption,
                order_index=len(blocks),
            ))
            continue
        heading = _HEADING_RE.match(line.strip())
        if heading:
            flush_paragraph()
            blocks.append(ParsedDocumentBlock(
                block_id=str(uuid.uuid4()),
                block_type="heading",
                text=heading.group(2).strip(),
                level=len(heading.group(1)),
                order_index=len(blocks),
            ))
            continue
        if not line.strip():
            flush_paragraph()
            continue
        if "$" in line or "\\(" in line or "\\[" in line:
            # Keep formulas in context instead of trying to evaluate them.
            pending.append(line)
        else:
            pending.append(line)
    flush_paragraph()

    if not blocks and markdown.strip():
        blocks.append(ParsedDocumentBlock(
            block_id=str(uuid.uuid4()),
            block_type="paragraph",
            text=markdown.strip(),
            order_index=0,
        ))
    return blocks


def _maybe_parse_via_extract(file_path: str, file_name: str, parsed_doc: ParsedDocument) -> bool:
    from data_agent.parsing.parsers.mineru_extract_parser import (
        agent_failure_should_retry_extract,
        parse_via_mineru_extract,
        should_prefer_mineru_extract,
    )

    if not should_prefer_mineru_extract(file_path, file_name):
        return False
    parse_via_mineru_extract(file_path, file_name, parsed_doc)
    return parsed_doc.parse_status != "failed" or bool(parsed_doc.blocks)


def _retry_agent_failure_with_extract(
    file_path: str,
    file_name: str,
    parsed_doc: ParsedDocument,
    exc: Exception,
) -> bool:
    from data_agent.parsing.parsers.mineru_extract_parser import (
        agent_failure_should_retry_extract,
        parse_via_mineru_extract,
        parse_via_mineru_extract_url,
    )

    err_code = exc.err_code if isinstance(exc, MinerUAgentError) else None
    if not agent_failure_should_retry_extract(str(exc), err_code):
        return False
    parsed_doc.warnings.append("MinerU Agent 超出轻量限制，自动切换 v4 精准解析 API。")
    if _is_url(file_path):
        parse_via_mineru_extract_url(file_path, file_name, parsed_doc)
    else:
        parse_via_mineru_extract(file_path, file_name, parsed_doc)
    return parsed_doc.parse_status != "failed" or bool(parsed_doc.blocks)


def parse_via_mineru_agent(
    file_path: str,
    file_name: str,
    parsed_doc: ParsedDocument,
    *,
    parse_mode: str | None = None,
) -> None:
    parsed_doc.parser_name = "mineru-agent"
    if _is_url(file_path):
        parse_via_mineru_agent_url(file_path, file_name, parsed_doc, parse_mode=parse_mode)
        return

    if not mineru_agent_supports(file_name):
        if _maybe_parse_via_extract(file_path, file_name, parsed_doc):
            return
        parsed_doc.parse_status = "failed"
        parsed_doc.warnings.append(
            f"MinerU Agent lightweight API does not support {Path(file_name).suffix.lower()} "
            "(legacy .doc/.ppt/.xls 需配置 Token 使用 v4 extract API)"
        )
        return

    if _maybe_parse_via_extract(file_path, file_name, parsed_doc):
        return

    try:
        task_id = _submit_file_task(file_path, file_name, parse_mode=parse_mode)
        raw_markdown, markdown_url = _poll_markdown(task_id)
        image_urls = _resolve_image_urls(markdown_url, raw_markdown)
        image_ocr = _build_image_ocr_map(raw_markdown, image_urls)
        complete, incompleteness_msg = assess_markdown_completeness(file_path, raw_markdown)
        if not complete:
            logger.warning("[MinerU Agent] %s", incompleteness_msg)
            parsed_doc.warnings.append(incompleteness_msg)
            if parsed_doc.parse_status != "failed":
                parsed_doc.parse_status = "degraded"
        markdown = normalize_mineru_markdown(raw_markdown)
        parsed_doc.blocks = markdown_to_parsed_blocks(
            markdown, image_urls=image_urls, image_ocr=image_ocr,
        )
        block_chars = sum(len(b.text or "") for b in parsed_doc.blocks)
        blocks_complete, blocks_msg = assess_markdown_completeness(
            file_path,
            "x" * block_chars if block_chars else "",
        )
        if not blocks_complete and blocks_msg not in parsed_doc.warnings:
            logger.warning("[MinerU Agent] %s (block text)", blocks_msg)
            parsed_doc.warnings.append(f"{blocks_msg} (extracted block text)")
        if not parsed_doc.blocks:
            parsed_doc.parse_status = "degraded"
            parsed_doc.warnings.append("MinerU Agent returned empty Markdown.")
        elif not complete or not blocks_complete:
            parsed_doc.parse_status = "degraded"
        else:
            parsed_doc.parse_status = "ok"
        if image_urls:
            parsed_doc.warnings.append(f"MinerU Agent images={len(image_urls)} ocr={len(image_ocr)}")
        parsed_doc.warnings.append(f"MinerU Agent task_id={task_id}")
        if parse_mode:
            parsed_doc.warnings.append(f"MinerU Agent mode={parse_mode}")
    except Exception as exc:
        if _retry_agent_failure_with_extract(file_path, file_name, parsed_doc, exc):
            return
        parsed_doc.parse_status = "failed"
        parsed_doc.warnings.append(f"MinerU Agent parse error: {exc}")


def extract_mineru_figure_blocks(
    file_path: str,
    file_name: str,
) -> tuple[list[ParsedDocumentBlock], list[str]]:
    """仅提取 MinerU 解析结果中的 figure 块（用于 DOCX 增强），失败时返回空列表。"""
    from data_agent.parsing.mineru_online import attempt_mineru_online
    from data_agent.parsing.parsers.mineru_agent_parser import mineru_agent_supports

    warnings: list[str] = []
    if not mineru_agent_supports(file_name):
        return [], [f"MinerU 不支持该格式: {Path(file_name).suffix.lower()}"]
    temp_doc = ParsedDocument(
        document_id=str(uuid.uuid4()),
        file_name=file_name,
        file_type="design_report",
        parser_name="mineru-agent",
        parse_status="ok",
    )
    if not attempt_mineru_online(file_path, file_name, temp_doc):
        warnings.extend(temp_doc.warnings)
        return [], warnings or ["MinerU 在线解析不可用或失败"]
    warnings.extend(temp_doc.warnings)
    if temp_doc.parse_status == "failed":
        return [], warnings
    figures = [b for b in temp_doc.blocks if b.block_type == "figure"]
    return figures, warnings


def parse_via_mineru_agent_url(
    url: str,
    file_name: str,
    parsed_doc: ParsedDocument,
    *,
    parse_mode: str | None = None,
) -> None:
    parsed_doc.parser_name = "mineru-agent"
    if not mineru_agent_supports(file_name):
        parsed_doc.parse_status = "failed"
        parsed_doc.warnings.append(f"MinerU Agent lightweight API does not support {Path(file_name).suffix.lower()}")
        return

    try:
        task_id = _submit_url_task(url, file_name, parse_mode=parse_mode)
        raw_markdown, markdown_url = _poll_markdown(task_id)
        image_urls = _resolve_image_urls(markdown_url, raw_markdown)
        image_ocr = _build_image_ocr_map(raw_markdown, image_urls)
        markdown = normalize_mineru_markdown(raw_markdown)
        parsed_doc.blocks = markdown_to_parsed_blocks(
            markdown, image_urls=image_urls, image_ocr=image_ocr,
        )
        parsed_doc.parse_status = "ok" if parsed_doc.blocks else "degraded"
        parsed_doc.warnings.append(f"MinerU Agent task_id={task_id}")
        if not parsed_doc.blocks:
            parsed_doc.warnings.append("MinerU Agent returned empty Markdown.")
    except Exception as exc:
        if _retry_agent_failure_with_extract(url, file_name, parsed_doc, exc):
            return
        parsed_doc.parse_status = "failed"
        parsed_doc.warnings.append(f"MinerU Agent URL parse error: {exc}")


__all__ = [
    "MinerUAgentError",
    "assess_markdown_completeness",
    "extract_mineru_figure_blocks",
    "markdown_to_parsed_blocks",
    "mineru_agent_enabled",
    "mineru_agent_supports",
    "normalize_mineru_markdown",
    "parse_via_mineru_agent",
    "parse_via_mineru_agent_url",
]
