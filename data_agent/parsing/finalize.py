"""Post-parse finalization: LLM enhancement and optional self-healing."""

from __future__ import annotations

import os
from pathlib import Path

from data_agent.parsing.schemas import ParsedDocument

_MMX_CLI_PATH = os.getenv("MMX_CLI_PATH", "/opt/homebrew/bin/mmx")
_VISION_CAPABLE_MODEL_HINTS = (
    "vl",
    "qwen-vl",
    "qwen2.5-vl",
    "qwen3-vl",
    "vision",
    "visual",
    "multimodal",
    "gpt-4o",
    "gpt-4.1",
    "gemini",
    "claude-3",
)


def _profile_uses_minimax_m2_text_api(profile) -> bool:
    model = str(getattr(profile, "model", "") or "").lower()
    base_url = str(getattr(profile, "base_url", "") or "").lower()
    return model.startswith("minimax-m2") and "minimax" in base_url


def _profile_supports_image_desc(profile) -> bool:
    if _profile_uses_minimax_m2_text_api(profile):
        return True
    model = str(getattr(profile, "model", "") or "").lower()
    return any(hint in model for hint in _VISION_CAPABLE_MODEL_HINTS)


def _resolve_llm_enhancement_flags(
    processing_mode: str | None,
    parser_type: str,
) -> dict[str, bool] | None:
    """Map processing_mode to LLM enhancer flags. None = skip LLM enhancement."""
    from data_agent.core.config import parsing_enable_image_desc

    mode = (processing_mode or "").strip().lower()
    flags: dict[str, bool] | None
    if mode in {"quick", "high_speed"}:
        return None
    if mode in {"standard", "optimal"}:
        flags = {
            "enable_correction": True,
            "enable_structure": True,
            "enable_formula": True,
            "enable_image_desc": False,
        }
    elif mode in {"deep", "enhanced"}:
        flags = {
            "enable_correction": True,
            "enable_structure": True,
            "enable_formula": True,
            "enable_image_desc": True,
        }
    elif mode == "high_accuracy":
        flags = {
            "enable_correction": True,
            "enable_structure": True,
            "enable_formula": True,
            "enable_image_desc": True,
        }
    elif not mode and parser_type in ("auto", "mineru_agent"):
        # 未指定 mode：auto / mineru_agent 默认 standard
        flags = {
            "enable_correction": True,
            "enable_structure": True,
            "enable_formula": True,
            "enable_image_desc": False,
        }
    else:
        return None

    if parsing_enable_image_desc():
        flags["enable_image_desc"] = True
    return flags


def _image_desc_enabled_for_mode(
    processing_mode: str | None,
    parser_type: str = "local",
) -> bool:
    """Whether embedded-figure VLM description should run for this parse."""
    from data_agent.core.config import parsing_enable_image_desc

    if parsing_enable_image_desc():
        return True
    flags = _resolve_llm_enhancement_flags(processing_mode, parser_type)
    return bool(flags and flags.get("enable_image_desc"))


def _check_image_desc_prerequisites(parsed_doc: ParsedDocument, *, enable_image_desc: bool) -> None:
    """检查嵌入图片提取与 vision LLM 的前置条件。"""
    if not enable_image_desc:
        return
    try:
        from data_agent.parsing.parsers import image_extractor  # noqa: F401

        _ = image_extractor.extract_embedded_images
    except (ImportError, AttributeError) as exc:
        parsed_doc.warnings.append(f"image_extractor 不可用: {exc}")

    from data_agent.core.llm_profiles import get_llm_profile

    light_vision = get_llm_profile("light_vision")
    vision = get_llm_profile("vision")
    for label, profile in (("LIGHT_VLM", light_vision), ("VLM", vision)):
        if profile.is_complete() and not _profile_supports_image_desc(profile):
            parsed_doc.warnings.append(
                f"{label} 模型可能不支持图片输入: {profile.model}"
            )
    if (
        not light_vision.is_complete()
        and not vision.is_complete()
        and not os.path.isfile(_MMX_CLI_PATH)
    ):
        parsed_doc.warnings.append(
            "图片描述未配置：请设置 LIGHT_VLM_* 或 VLM_*，或安装 mmx CLI 作为降级"
        )


def _apply_llm_enhancement(
    parsed_doc: ParsedDocument,
    file_path: str,
    *,
    processing_mode: str | None,
    parser_type: str,
) -> None:
    """对 auto / mineru_agent 及 DOCX 解析结果应用 LLM 增强层。"""
    if parsed_doc.parse_status == "failed" or not parsed_doc.blocks:
        return

    flags = _resolve_llm_enhancement_flags(processing_mode, parser_type)
    if flags is None and parsed_doc.parser_name != "python-docx":
        return

    # DOCX + quick 模式：仅构建章节树，不调用 LLM
    if flags is None and parsed_doc.parser_name == "python-docx":
        from data_agent.parsing.enhancers.llm_enhancer import _apply_chapter_tree

        _apply_chapter_tree(parsed_doc)
        return

    if flags is None:
        return

    from data_agent.parsing.enhancers.llm_enhancer import enhance_parsed_document_sync

    # python-docx 解析结果无 OCR 错误，跳过纠错步骤节省时间
    if parsed_doc.parser_name == "python-docx" and "enable_correction" in flags:
        flags = dict(flags, enable_correction=False)

    if flags.get("enable_image_desc"):
        _check_image_desc_prerequisites(parsed_doc, enable_image_desc=True)

    enhance_parsed_document_sync(
        parsed_doc, file_path, processing_mode=processing_mode, **flags
    )


def _should_run_parse_calibration(
    processing_mode: str | None,
    parser_type: str,
    parsed_doc: ParsedDocument,
) -> bool:
    if parsed_doc.parse_status == "failed" or not parsed_doc.blocks:
        return False

    from data_agent.core.config import parsing_calibration_enabled

    if not parsing_calibration_enabled():
        return False

    mode = (processing_mode or "").strip().lower()
    if mode in {"quick", "high_speed"}:
        return False
    if mode in {"standard", "optimal", "high_accuracy", "deep", "enhanced"}:
        return True
    return not mode and (
        parser_type in {"auto", "mineru", "mineru_agent"}
        or parsed_doc.parser_name in {"mineru-local", "mineru-agent", "mineru-extract"}
    )


def _apply_parse_calibration(
    parsed_doc: ParsedDocument,
    *,
    processing_mode: str | None,
    parser_type: str,
    enable_llm: bool = True,
) -> None:
    if not _should_run_parse_calibration(processing_mode, parser_type, parsed_doc):
        return

    def _calibration_progress(completed: int, total: int) -> None:
        if total <= 0:
            return
        from data_agent.parsing.parse_preview_progress import report_progress

        progress = 60 + int(35 * completed / total)
        report_progress(progress, f"VLM 校准 {completed}/{total}")

    try:
        from data_agent.agents.parse_calibrator import ParseRationalityCalibratorAgent
        from data_agent.core.config import (
            get_parsing_calibration_max_blocks,
            get_parsing_calibration_max_concurrency,
        )

        total_blocks = min(len(parsed_doc.blocks), get_parsing_calibration_max_blocks())
        if enable_llm and total_blocks > 0:
            from data_agent.parsing.parse_preview_progress import report_progress

            report_progress(55, f"开始 VLM 校准（0/{total_blocks}）…")

        records = ParseRationalityCalibratorAgent(
            max_blocks=get_parsing_calibration_max_blocks(),
            enable_llm=enable_llm,
        ).calibrate_document_sync(
            parsed_doc,
            max_concurrency=get_parsing_calibration_max_concurrency(),
            progress_callback=_calibration_progress if enable_llm else None,
        )
    except Exception as exc:
        parsed_doc.enhancement_log.append(
            {"step": "parse_calibration", "status": "error", "detail": str(exc)}
        )
        return

    parsed_doc.calibration_records = records
    critical_count = sum(1 for record in records if record.severity == "critical")
    parsed_doc.enhancement_log.append(
        {
            "step": "parse_calibration",
            "status": "ok",
            "detail": f"flagged {len(records)} issue(s), critical={critical_count}",
        }
    )
    if critical_count:
        parsed_doc.warnings.append(f"解析合理性校准发现 {critical_count} 个严重可疑结果，需人工复核。")


def _apply_figure_crops(
    parsed_doc: ParsedDocument,
    file_path: str,
    *,
    figure_storage_dir: str | None = None,
) -> dict[str, str | None]:
    if parsed_doc.parse_status == "failed" or not parsed_doc.blocks or not file_path:
        return {}

    from data_agent.parsing.enhancers.llm_enhancer import _is_figure_block, crop_figure_blocks

    figure_blocks = [b for b in parsed_doc.blocks if _is_figure_block(b)]
    if not figure_blocks:
        return {}

    from data_agent.parsing.parse_preview_progress import report_progress

    report_progress(30, f"正在裁剪 figure 原图（0/{len(figure_blocks)}）…")
    try:
        if figure_storage_dir:
            Path(figure_storage_dir).mkdir(parents=True, exist_ok=True)
        return crop_figure_blocks(
            parsed_doc,
            file_path,
            figure_storage_dir=figure_storage_dir,
        )
    except Exception as exc:
        parsed_doc.enhancement_log.append(
            {"step": "figure_crop", "status": "error", "detail": str(exc)}
        )
        return {}


def _apply_figure_vision(
    parsed_doc: ParsedDocument,
    file_path: str,
    *,
    processing_mode: str | None,
    parser_type: str = "local",
    image_paths: dict[str, str | None] | None = None,
    figure_storage_dir: str | None = None,
) -> None:
    from data_agent.core.config import get_parsing_image_desc_max_concurrency

    if not _image_desc_enabled_for_mode(processing_mode, parser_type):
        return
    if parsed_doc.parse_status == "failed" or not parsed_doc.blocks:
        return
    if not file_path:
        return

    _check_image_desc_prerequisites(parsed_doc, enable_image_desc=True)

    from data_agent.parsing.enhancers.llm_enhancer import _is_figure_block, describe_figure_blocks

    figure_blocks = [b for b in parsed_doc.blocks if _is_figure_block(b)]
    if not figure_blocks:
        return

    def _figure_progress(completed: int, total: int) -> None:
        if total <= 0:
            return
        from data_agent.parsing.parse_preview_progress import report_progress

        progress = 35 + int(19 * completed / total)
        report_progress(progress, f"Vision 描述 {completed}/{total}")

    from data_agent.parsing.parse_preview_progress import report_progress

    report_progress(35, f"开始 Vision 描述（0/{len(figure_blocks)}）…")

    mode = (processing_mode or "").strip().lower()
    high_accuracy = mode in {"high_accuracy", "deep", "enhanced"}
    try:
        describe_figure_blocks(
            parsed_doc,
            file_path,
            high_accuracy=high_accuracy,
            max_concurrency=get_parsing_image_desc_max_concurrency(),
            progress_callback=_figure_progress,
            image_paths=image_paths,
            figure_storage_dir=figure_storage_dir,
        )
    except Exception as exc:
        parsed_doc.enhancement_log.append(
            {"step": "image_desc", "status": "error", "detail": str(exc)}
        )


def _apply_office_embedded_figures(
    parsed_doc: ParsedDocument,
    file_path: str,
    *,
    processing_mode: str | None,
    parser_type: str,
    figure_storage_dir: str | None = None,
) -> None:
    from data_agent.parsing.office_figure_blocks import (
        materialize_docx_embedded_figures,
        should_materialize_docx_figures,
    )

    file_name = parsed_doc.file_name or Path(file_path).name
    if not should_materialize_docx_figures(
        file_path,
        file_name,
        parsed_doc,
        processing_mode=processing_mode,
        parser_type=parser_type,
    ):
        return
    materialize_docx_embedded_figures(
        parsed_doc,
        file_path,
        file_name,
        figure_storage_dir=figure_storage_dir,
    )


def finalize_parsed_document(
    parsed_doc: ParsedDocument,
    *,
    parser_type: str = "local",
    processing_mode: str | None = None,
    file_path: str = "",
    skip_enhancement: bool = False,
    figure_storage_dir: str | None = None,
) -> ParsedDocument:
    """LLM 增强 + 可选 self-healing pipeline."""
    _apply_office_embedded_figures(
        parsed_doc,
        file_path,
        processing_mode=processing_mode,
        parser_type=parser_type,
        figure_storage_dir=figure_storage_dir,
    )
    if skip_enhancement:
        parsed_doc.structuring_warnings.append("postprocess skipped for parse preview")
        image_paths = _apply_figure_crops(
            parsed_doc,
            file_path,
            figure_storage_dir=figure_storage_dir,
        )
        _apply_figure_vision(
            parsed_doc,
            file_path,
            processing_mode=processing_mode,
            parser_type=parser_type,
            image_paths=image_paths or None,
            figure_storage_dir=figure_storage_dir,
        )
        _apply_parse_calibration(
            parsed_doc,
            processing_mode=processing_mode,
            parser_type=parser_type,
            enable_llm=True,
        )
        return parsed_doc

    if (
        parsed_doc.parser_name not in {"html_parser", "pptx_zip_parser"}
        and (
            parser_type in ("auto", "mineru_agent")
            or parsed_doc.parser_name in (
                "mineru-agent",
                "mineru-extract",
                "python-docx",
            )
        )
    ):
        _apply_llm_enhancement(
            parsed_doc,
            file_path,
            processing_mode=processing_mode,
            parser_type=parser_type,
        )

    _apply_parse_calibration(
        parsed_doc,
        processing_mode=processing_mode,
        parser_type=parser_type,
    )

    if not processing_mode:
        return parsed_doc

    mode = processing_mode.upper()
    if mode == "HIGH_SPEED":
        return parsed_doc
    # quick / standard / deep 仅控制 LLM 增强层，不进入 format_guard
    if mode not in {"OPTIMAL", "HIGH_SPEED", "HIGH_ACCURACY"}:
        return parsed_doc

    from data_agent.core.config import is_structuring_enabled

    if not is_structuring_enabled():
        parsed_doc.structuring_warnings.append("structuring disabled (STRUCTURING_ENABLED=0)")
        return parsed_doc

    from data_agent.agents.format_guard.pipeline import SelfHealingPipeline

    result = SelfHealingPipeline().run_sync(parsed_doc, processing_mode=mode)  # type: ignore[arg-type]
    result.document.self_healing_records = [
        {
            "block_id": record.block_id,
            "damage_types": [damage.value for damage in record.damage_types],
            "text_before": record.text_before,
            "text_after": record.text_after,
            "repair_status": record.repair_status,
            "model_id": record.model_id,
            "latency_ms": record.latency_ms,
        }
        for record in result.repair_records
        if record.repair_status == "ok" and record.text_before != record.text_after
    ]
    return result.document


def parse_and_heal_document(
    file_path: str,
    file_name: str,
    parser_type: str = "local",
    processing_mode: str = "OPTIMAL",
):
    """Parse then run full self-healing pipeline; returns StructuredCorpusResult."""
    from data_agent.agents.format_guard.pipeline import SelfHealingPipeline
    from data_agent.agents.format_guard.schemas import StructuredCorpusResult

    from data_agent.parsing.parser_core import parse_uploaded_document

    parsed_doc = parse_uploaded_document(file_path, file_name, parser_type)
    mode = (processing_mode or "OPTIMAL").upper()
    return SelfHealingPipeline().run_sync(parsed_doc, processing_mode=mode)  # type: ignore[arg-type]
