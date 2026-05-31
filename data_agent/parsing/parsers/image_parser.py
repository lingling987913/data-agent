"""Standalone image attachment parser with MinerU / Vision fallback chain."""

from __future__ import annotations

import json
import logging
import os
import uuid
from pathlib import Path
from time import perf_counter

from data_agent.parsing.fallback_trace import record_parser_fallback
from data_agent.parsing.schemas import ParsedDocument, ParsedDocumentBlock

logger = logging.getLogger(__name__)

IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".jp2", ".webp", ".gif", ".bmp")


def is_image_file(file_name: str) -> bool:
    return Path(file_name).suffix.lower() in IMAGE_EXTENSIONS


def inspect_image_quality(file_path: str) -> dict[str, object]:
    size = os.path.getsize(file_path) if os.path.exists(file_path) else 0
    quality: dict[str, object] = {
        "file_size_bytes": size,
        "blur": "unknown",
        "brightness": "unknown",
        "skew": "unknown",
        "ocr_confidence": None,
        "requires_human_confirmation": True,
    }
    try:
        from PIL import Image, ImageStat  # type: ignore

        with Image.open(file_path) as image:
            grayscale = image.convert("L")
            stat = ImageStat.Stat(grayscale)
            brightness = float(stat.mean[0])
            quality.update(
                {
                    "width": image.width,
                    "height": image.height,
                    "brightness": round(brightness, 2),
                    "brightness_status": "low" if brightness < 60 else "high" if brightness > 220 else "ok",
                }
            )
    except Exception as exc:
        quality["warning"] = f"image quality probe unavailable: {exc}"
    return quality


def parse_image_minimal(file_path: str, file_name: str, parsed_doc: ParsedDocument) -> None:
    parsed_doc.parser_name = "image_minimal_parser"
    parsed_doc.file_type = "image_document"
    parsed_doc.parse_status = "degraded"
    quality = inspect_image_quality(file_path)
    parsed_doc.blocks = [
        ParsedDocumentBlock(
            block_id=str(uuid.uuid4()),
            block_type="figure_caption",
            text=(
                f"图片附件 {file_name}; visual_element=image; "
                "confidence=0.2; extraction_method=low_confidence_visual_summary; requires_human_confirmation=true; "
                f"quality={json.dumps(quality, ensure_ascii=False)}"
            ),
            order_index=0,
            confidence=0.2,
        )
    ]
    parsed_doc.warnings.append("图片已记录低置信视觉摘要；尚未执行高精度图表/工程图还原。")


def parse_image_via_vision(
    file_path: str,
    file_name: str,
    parsed_doc: ParsedDocument,
    *,
    processing_mode: str | None = None,
) -> bool:
    """Use vision LLM (with mmx CLI fallback) to describe/OCR the image."""
    from data_agent.parsing.enhancers.llm_enhancer import _vision_describe

    high_accuracy = (processing_mode or "OPTIMAL").upper() == "HIGH_ACCURACY"
    description = _vision_describe(file_path, high_accuracy=high_accuracy)
    if not description or len(description.strip()) < 4:
        return False

    block_id = str(uuid.uuid4())
    parsed_doc.parser_name = "vision_llm_parser"
    parsed_doc.file_type = "image_document"
    parsed_doc.parse_status = "ok"
    parsed_doc.blocks = [
        ParsedDocumentBlock(
            block_id=block_id,
            block_type="figure",
            text=description.strip(),
            caption=f"图片附件 {file_name}",
            confidence=0.65,
            order_index=0,
        ),
        ParsedDocumentBlock(
            block_id=str(uuid.uuid4()),
            block_type="paragraph",
            text=description.strip(),
            confidence=0.65,
            order_index=1,
        ),
    ]
    parsed_doc.warnings.append("图片经 Vision LLM 解析；工程图/图表结构化数据仍需人工确认。")
    return True


def _mineru_succeeded(parsed_doc: ParsedDocument) -> bool:
    return parsed_doc.parse_status != "failed" and bool(parsed_doc.blocks)


def parse_image_auto(
    file_path: str,
    file_name: str,
    parsed_doc: ParsedDocument,
    *,
    processing_mode: str | None = None,
) -> None:
    """Image fallback chain: local MinerU -> online (v4/agent) -> Vision LLM -> minimal summary."""
    from data_agent.parsing.mineru_config import mineru_prefer_local
    from data_agent.parsing.mineru_online import attempt_mineru_online
    from data_agent.parsing.parsers.mineru_local_http_parser import (
        mineru_local_supports,
        parse_via_mineru_local_http,
    )

    mode = (processing_mode or "OPTIMAL").upper()
    logs = parsed_doc.parser_fallback_logs
    parsed_doc.file_type = "image_document"
    prefer_local = mineru_prefer_local()

    def _try_local(*, next_fallback: str, fail_warning: str) -> bool:
        if not mineru_local_supports(file_name):
            return False
        start = perf_counter()
        try:
            parse_via_mineru_local_http(file_path, file_name, parsed_doc)
            elapsed_ms = int((perf_counter() - start) * 1000)
            if _mineru_succeeded(parsed_doc):
                return True
            record_parser_fallback(
                logs,
                source_parser="mineru_local",
                fallback_parser=next_fallback,
                reason="local_failed_or_empty",
                recovered=False,
                elapsed_ms=elapsed_ms,
            )
            parsed_doc.warnings.append(fail_warning)
        except Exception as exc:
            record_parser_fallback(
                logs,
                source_parser="mineru_local",
                fallback_parser=next_fallback,
                reason=str(exc),
                recovered=False,
            )
            parsed_doc.warnings.append(f"MinerU 本地 HTTP 异常: {exc}")
        parsed_doc.blocks = []
        parsed_doc.parse_status = "ok"
        return False

    if mode != "HIGH_SPEED":
        if prefer_local and _try_local(
            next_fallback="mineru_extract",
            fail_warning="MinerU 本地 HTTP 图片解析失败，尝试在线 MinerU。",
        ):
            return

        if attempt_mineru_online(file_path, file_name, parsed_doc):
            return

        if not prefer_local and _try_local(
            next_fallback="vision_llm_parser",
            fail_warning="MinerU 本地 HTTP 图片解析失败，降级为 Vision LLM。",
        ):
            return

    if mode != "HIGH_SPEED":
        start = perf_counter()
        if parse_image_via_vision(file_path, file_name, parsed_doc, processing_mode=processing_mode):
            elapsed_ms = int((perf_counter() - start) * 1000)
            record_parser_fallback(
                logs,
                source_parser="mineru_local" if mode != "HIGH_SPEED" else "high_speed",
                fallback_parser="vision_llm_parser",
                reason="vision_recovered",
                recovered=True,
                elapsed_ms=elapsed_ms,
            )
            return
        record_parser_fallback(
            logs,
            source_parser="vision_llm_parser",
            fallback_parser="image_minimal_parser",
            reason="vision_unavailable_or_empty",
            recovered=False,
            elapsed_ms=int((perf_counter() - start) * 1000),
        )
        parsed_doc.warnings.append("Vision LLM 不可用或未返回有效描述，降级为低置信摘要。")
        parsed_doc.blocks = []

    start = perf_counter()
    parse_image_minimal(file_path, file_name, parsed_doc)
    elapsed_ms = int((perf_counter() - start) * 1000)
    if parsed_doc.parse_status != "failed":
        record_parser_fallback(
            logs,
            source_parser="vision_llm_parser" if mode != "HIGH_SPEED" else "high_speed",
            fallback_parser="image_minimal_parser",
            reason="high_speed" if mode == "HIGH_SPEED" else "final_fallback",
            recovered=bool(parsed_doc.blocks),
            elapsed_ms=elapsed_ms,
        )


__all__ = [
    "IMAGE_EXTENSIONS",
    "inspect_image_quality",
    "is_image_file",
    "parse_image_auto",
    "parse_image_minimal",
    "parse_image_via_vision",
]
