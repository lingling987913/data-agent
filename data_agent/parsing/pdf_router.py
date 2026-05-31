"""PDF auto-parse router with MinerU fallback chain."""

from __future__ import annotations

from pathlib import Path
from time import perf_counter

from data_agent.parsing.fallback_trace import record_parser_fallback
from data_agent.parsing.mineru_config import mineru_prefer_local
from data_agent.parsing.mineru_online import attempt_mineru_online
from data_agent.parsing.pdf_postprocess import apply_pdf_postprocess
from data_agent.parsing.parsers.mineru_agent_parser import mineru_agent_supports
from data_agent.parsing.parsers.mineru_local_http_parser import (
    mineru_local_enabled,
    mineru_local_supports,
    parse_via_mineru_local_http,
)
from data_agent.parsing.parsers.pdf_parser import parse_pdf
from data_agent.parsing.schemas import ParsedDocument


def _try_mineru_local(
    file_path: str,
    file_name: str,
    parsed_doc: ParsedDocument,
    *,
    fallback_parser: str,
    fallback_warning: str,
) -> bool:
    """Attempt local MinerU HTTP parse. Returns True when blocks were produced."""
    if not mineru_local_supports(file_name):
        return False

    logs = parsed_doc.parser_fallback_logs
    start = perf_counter()
    try:
        parse_via_mineru_local_http(file_path, file_name, parsed_doc)
        elapsed_ms = int((perf_counter() - start) * 1000)
        if parsed_doc.parse_status != "failed" and parsed_doc.blocks:
            return True
        record_parser_fallback(
            logs,
            source_parser="mineru_local",
            fallback_parser=fallback_parser,
            reason="local_failed_or_empty",
            recovered=False,
            elapsed_ms=elapsed_ms,
        )
        parsed_doc.warnings.append(fallback_warning)
    except Exception as exc:
        record_parser_fallback(
            logs,
            source_parser="mineru_local",
            fallback_parser=fallback_parser,
            reason=str(exc),
            recovered=False,
        )
        parsed_doc.warnings.append(f"MinerU 本地 HTTP 异常: {exc}")
    return False


def parse_pdf_auto(
    file_path: str,
    file_name: str,
    parsed_doc: ParsedDocument,
    *,
    processing_mode: str | None = None,
) -> None:
    """PDF/图片降级: 本地 MinerU -> 在线 MinerU (v4/agent) -> pdftotext/图片摘要。"""
    mode = (processing_mode or "OPTIMAL").upper()
    logs = parsed_doc.parser_fallback_logs
    prefer_local = mineru_prefer_local()

    def _mineru_online_attempted() -> bool:
        return any(
            str(log.get("source_parser") or "").startswith("mineru")
            for log in logs
        )

    if mode != "HIGH_SPEED":
        if prefer_local and _try_mineru_local(
            file_path,
            file_name,
            parsed_doc,
            fallback_parser="mineru_extract",
            fallback_warning="MinerU 本地 HTTP 解析失败，尝试在线 MinerU。",
        ):
            apply_pdf_postprocess(parsed_doc)
            return

        if attempt_mineru_online(file_path, file_name, parsed_doc):
            apply_pdf_postprocess(parsed_doc)
            return

        if (
            not prefer_local
            and _try_mineru_local(
                file_path,
                file_name,
                parsed_doc,
                fallback_parser="pdftotext",
                fallback_warning="MinerU 本地 HTTP 解析失败，降级为 pdftotext。",
            )
        ):
            apply_pdf_postprocess(parsed_doc)
            return

    if (
        mode != "HIGH_SPEED"
        and mineru_agent_supports(file_name)
        and _mineru_online_attempted()
        and not mineru_local_supports(file_name)
    ):
        if not mineru_local_enabled():
            parsed_doc.warnings.append(
                "MinerU 本地 HTTP 未启用（MINERU_LOCAL_ENABLED=0），将降级为 pdftotext。"
            )

    parsed_doc.blocks = []
    is_image = Path(file_name).suffix.lower() in (".png", ".jpg", ".jpeg", ".jp2", ".webp", ".gif", ".bmp")
    start = perf_counter()
    if is_image:
        from data_agent.parsing.parsers.image_parser import parse_image_auto

        parse_image_auto(file_path, file_name, parsed_doc, processing_mode=processing_mode)
    else:
        parse_pdf(file_path, parsed_doc)
        elapsed_ms = int((perf_counter() - start) * 1000)
        if parsed_doc.parse_status != "failed":
            if mode == "HIGH_SPEED":
                source_parser = "high_speed"
                reason = "high_speed"
            else:
                source_parser = "mineru_agent"
                for candidate in ("mineru_local", "mineru_extract", "mineru_agent"):
                    if any(log.get("source_parser") == candidate for log in logs):
                        source_parser = candidate
                        break
                reason = "final_fallback"
            record_parser_fallback(
                logs,
                source_parser=source_parser,
                fallback_parser="pdftotext",
                reason=reason,
                recovered=bool(parsed_doc.blocks),
                elapsed_ms=elapsed_ms,
            )
            parsed_doc.warnings.append("已使用 pdftotext 兜底解析。")
        apply_pdf_postprocess(parsed_doc)
        return
    elapsed_ms = int((perf_counter() - start) * 1000)
    if parsed_doc.parse_status != "failed" and parsed_doc.parser_name == "image_minimal_parser":
        parsed_doc.warnings.append("已使用图片低置信摘要兜底解析。")
