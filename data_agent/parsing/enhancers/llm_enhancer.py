"""
LLM 增强层 — 同步版本
对解析后的 ParsedDocument 进行：OCR 纠错、缺失章节补全、公式 LaTeX 化、图片描述、章节树构建
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable

from pydantic import Field

from data_agent.parsing.schemas import ParsedDocument, ParsedDocumentBlock

import logging

logger = logging.getLogger(__name__)

_FORMULA_RE = re.compile(
    r"[$\\]|\\frac|\\sum|\\int|σ|σ|±|≤|≥|≠|∞|∑|∫|√|α|β|γ|δ|θ|λ|μ|π|Ω|°|²|³"
)
_IMAGE_MD_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
_CORRECTION_BATCH_SIZE = 8
_MAX_CORRECTION_SECONDS = 45
_MAX_CONSECUTIVE_BATCH_FAILURES = 2
_LLM_TIMEOUT_SECONDS = 30
_MMX_CLI_PATH = os.getenv("MMX_CLI_PATH", "/opt/homebrew/bin/mmx")
_VISION_DESCRIBE_PROMPT = (
    "请详细描述这张图片的内容，特别是其中的文字、表格、公式、流程图、坐标轴、图例和曲线趋势等元素。"
    "如果图片包含多个子图，请按从上到下、从左到右逐一描述每个子图，不要只描述第一个子图。"
    "回答要简洁但完整，用中文回答。"
)
_THINK_BLOCK_RE = re.compile(r"<think\b[^>]*>.*?</think>", re.IGNORECASE | re.DOTALL)
_FENCED_THINK_RE = re.compile(r"```(?:thinking|think)\s*.*?```", re.IGNORECASE | re.DOTALL)
_UNUSABLE_VISION_PATTERNS = (
    "没有看到",
    "未看到",
    "无法看到",
    "看不到",
    "没有提供图片",
    "没有图片",
    "上传图片",
    "提供图片",
    "图片链接",
    "image is not provided",
    "no image",
    "cannot see",
    "can't see",
)
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


def _append_log(parsed_doc: ParsedDocument, step: str, status: str, detail: str = "") -> None:
    parsed_doc.enhancement_log.append({"step": step, "status": status, "detail": detail})


def _get_agent(*, instructions: list[str], role: str = "parsing"):
    from agno.agent import Agent

    from data_agent.core.llm_profiles import get_llm_profile, profile_to_openai_chat

    profile = get_llm_profile(role)  # type: ignore[arg-type]
    model = profile_to_openai_chat(profile)
    try:
        model.timeout = _LLM_TIMEOUT_SECONDS  # type: ignore
    except Exception:
        pass
    return Agent(
        id="data-agent:parsing-enhancer",
        name="ParsingEnhancer",
        model=model,
        instructions=instructions,
        markdown=False,
    )


class _LLMEnhancerError(Exception):
    """LLM 调用失败（含 agno 将 API 错误写入 response.content 的情况）。"""


def _is_fatal_llm_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "rate limit" in msg or "429" in msg


def _run_agent(agent, prompt: str) -> str:
    """同步调用 LLM Agent"""
    response = agent.run(prompt)
    status = getattr(response, "status", None)
    if status is not None:
        from agno.run.base import RunStatus

        if status == RunStatus.error:
            detail = getattr(response, "content", None)
            raise _LLMEnhancerError(str(detail or "LLM agent run failed"))
    content = getattr(response, "content", response)
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    return str(content)


def _build_chapter_tree(blocks: list[ParsedDocumentBlock]) -> list[dict]:
    """从 heading blocks 构建嵌套章节树"""
    tree: list[dict] = []
    stack: list[dict] = []
    for b in blocks:
        if b.block_type != "heading" or not b.text:
            continue
        level = b.level or 1  # 直接用 block.level 字段
        node: dict = {"title": b.text, "level": level, "block_ids": [b.block_id], "children": []}
        while stack and stack[-1]["level"] >= level:
            stack.pop()
        if stack:
            stack[-1]["children"].append(node)
        else:
            tree.append(node)
        stack.append(node)
    return tree


def _collect_heading_blocks(blocks: list[ParsedDocumentBlock]) -> list[ParsedDocumentBlock]:
    return [b for b in blocks if b.block_type == "heading" and b.text]


def _looks_like_formula(text: str) -> bool:
    return bool(_FORMULA_RE.search(text))


def _is_figure_block(block: ParsedDocumentBlock) -> bool:
    block_type = (block.block_type or "").strip().lower()
    if block_type in {"figure", "image"}:
        return True
    if block.text and _IMAGE_MD_RE.search(block.text):
        return True
    from data_agent.parsing.figure_text import looks_like_image_ref

    if looks_like_image_ref(block.text or "") and block.bbox and block.page_hint:
        return True
    return False


def _normalize_figure_blocks(blocks: list[ParsedDocumentBlock]) -> None:
    from data_agent.parsing.figure_text import looks_like_image_ref

    for block in blocks:
        if not _is_figure_block(block):
            continue
        if (block.block_type or "").strip().lower() not in {"figure", "image"}:
            block.block_type = "figure"
        text = (block.text or "").strip()
        if looks_like_image_ref(text) or text == "[figure]":
            if not block.image_ref and looks_like_image_ref(text):
                block.image_ref = text
            if text != "[figure]":
                block.text = "[figure]"


def _correct_blocks(parsed_doc: ParsedDocument, *, enable: bool) -> None:
    """OCR 纠错：批量调用 LLM 修正文本中的符号错误"""
    if not enable or not parsed_doc.blocks:
        _append_log(parsed_doc, "correction", "skipped", "disabled or empty")
        return

    agent = _get_agent(instructions=[
        "你是航天/GNC 技术文档 OCR 纠错专家。",
        "修复 OCR/解析引入的符号错误（如 3g→3σ、希腊字母、上下标、标点），保持原意。",
        "只返回 JSON 数组，每项 {\"block_id\": \"...\", \"text\": \"...\"}，不要解释。",
    ])

    import time as _time
    corrections: dict[str, str] = {}
    blocks = [b for b in parsed_doc.blocks if b.text.strip() and b.block_type != "heading"]
    t_start = _time.monotonic()
    consecutive_failures = 0
    for start in range(0, len(blocks), _CORRECTION_BATCH_SIZE):
        if _time.monotonic() - t_start > _MAX_CORRECTION_SECONDS:
            _append_log(parsed_doc, "correction", "skipped", f"timeout after {start}/{len(blocks)} blocks")
            break
        batch = blocks[start : start + _CORRECTION_BATCH_SIZE]
        payload = [{"block_id": b.block_id, "text": b.text[:800]} for b in batch]
        prompt = (
            "纠正以下文本块中的 OCR/符号错误，输出 JSON 数组：\n"
            f"{json.dumps(payload, ensure_ascii=False)}"
        )
        try:
            raw = _run_agent(agent, prompt)
            match = re.search(r"\[.*\]", raw, re.DOTALL)
            if not match:
                raise ValueError(f"no JSON array in response: {raw[:200]!r}")
            for item in json.loads(match.group()):
                bid = str(item.get("block_id", ""))
                text = str(item.get("text", "")).strip()
                if bid and text:
                    corrections[bid] = text
            consecutive_failures = 0
        except Exception as exc:
            consecutive_failures += 1
            logger.error("[LLMEnhancer] correction batch failed: %s", exc)
            _append_log(parsed_doc, "correction", "error", str(exc))
            if _is_fatal_llm_error(exc) or consecutive_failures >= _MAX_CONSECUTIVE_BATCH_FAILURES:
                reason = "rate limited" if _is_fatal_llm_error(exc) else f"{consecutive_failures} consecutive failures"
                _append_log(parsed_doc, "correction", "skipped", f"aborted after {reason}")
                break
            continue

    applied = 0
    for block in parsed_doc.blocks:
        if block.block_id in corrections:
            block.text = corrections[block.block_id]
            applied += 1
    _append_log(parsed_doc, "correction", "ok", f"applied {applied}/{len(blocks)} blocks")


def _infer_missing_sections(parsed_doc: ParsedDocument) -> None:
    """推断缺失的章节（跳号、缺子节）"""
    headings = _collect_heading_blocks(parsed_doc.blocks)
    if len(headings) < 3:
        _append_log(parsed_doc, "completion", "skipped", "too few headings")
        return

    agent = _get_agent(instructions=[
        "你是技术文档结构分析专家。",
        "根据已有章节标题，判断是否存在明显缺失的章节（如跳号、缺子节）。",
        "返回 JSON：{\"missing\": [{\"title\": \"...\", \"level\": 2, \"reason\": \"...\"}]}",
    ])

    heading_list = [{"title": h.text, "level": h.level or 1} for h in headings]
    prompt = f"已有章节：\n{json.dumps(heading_list, ensure_ascii=False)}"
    try:
        raw = _run_agent(agent, prompt)
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            raise ValueError(f"no JSON object: {raw[:200]}")
        result = json.loads(match.group())
        missing = result.get("missing", [])
        _append_log(parsed_doc, "completion", "ok", f"inferred {len(missing)} missing sections")
    except Exception as exc:
        logger.error("[LLMEnhancer] completion failed: %s", exc)
        _append_log(parsed_doc, "completion", "error", str(exc))


def _extract_formulas(parsed_doc: ParsedDocument, *, enable: bool) -> None:
    """识别含公式的 block 并转为 LaTeX"""
    if not enable:
        _append_log(parsed_doc, "formula", "skipped", "disabled")
        return

    formula_blocks = [b for b in parsed_doc.blocks if b.text and _looks_like_formula(b.text)]
    if not formula_blocks:
        _append_log(parsed_doc, "formula", "ok", "no formula blocks found")
        return

    agent = _get_agent(role="formula", instructions=[
        "你是数学公式识别专家。",
        "将含数学内容的文本转为 LaTeX，保留工程符号（σ、± 等）。",
        "返回 JSON 数组：[{\"block_id\": \"...\", \"latex\": \"...\"}]",
    ])

    # 分批处理，每批最多 8 个 block，总超时 45 秒
    _FORMULA_BATCH = 8
    _FORMULA_TIMEOUT = 45
    t_formula_start = __import__("time").monotonic()
    total_extracted = 0
    for start in range(0, len(formula_blocks), _FORMULA_BATCH):
        if __import__("time").monotonic() - t_formula_start > _FORMULA_TIMEOUT:
            _append_log(parsed_doc, "formula", "skipped", f"timeout after {total_extracted}/{len(formula_blocks)}")
            return
        batch = formula_blocks[start:start + _FORMULA_BATCH]
        payload = [{"block_id": b.block_id, "text": b.text[:500]} for b in batch]
        prompt = f"将以下文本中的公式部分转为 LaTeX：\n{json.dumps(payload, ensure_ascii=False)}"
        try:
            raw = _run_agent(agent, prompt)
            match = re.search(r"\[.*\]", raw, re.DOTALL)
            if not match:
                raise ValueError(f"no JSON array: {raw[:200]}")
            for item in json.loads(match.group()):
                bid = str(item.get("block_id", ""))
                latex = str(item.get("latex", "")).strip()
                if bid and latex:
                    for b in parsed_doc.blocks:
                        if b.block_id == bid:
                            b.formula_latex = latex  # type: ignore
                            total_extracted += 1
                            break
        except Exception as exc:
            logger.error("[LLMEnhancer] formula batch failed: %s", exc)
            _append_log(parsed_doc, "formula", "error", str(exc))
            continue
    _append_log(parsed_doc, "formula", "ok", f"extracted {total_extracted}/{len(formula_blocks)} formulas")


def _mineru_ocr_text(block: ParsedDocumentBlock, alt_text: str) -> str:
    """优先使用 MinerU OCR 结果（存在 caption 且与 alt 不同或 alt 为空）。"""
    caption = (block.caption or "").strip()
    alt = (alt_text or "").strip()
    if caption and len(caption) > 4:
        if not alt or caption != alt or len(caption) > len(alt) + 4:
            return caption
    if alt and len(alt) > 4 and not alt.lower().startswith("image"):
        return alt
    return ""


def _mmx_cli_path() -> str:
    if os.path.isfile(_MMX_CLI_PATH):
        return _MMX_CLI_PATH
    from shutil import which

    return which("mmx") or _MMX_CLI_PATH


def sanitize_vision_output(text: str) -> str:
    """Remove model thinking wrappers and obvious prompt echo from VLM output."""
    cleaned = _FENCED_THINK_RE.sub("", text or "")
    cleaned = _THINK_BLOCK_RE.sub("", cleaned)
    cleaned = re.sub(r"^\s*(?:assistant|助手)\s*[:：]\s*", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip()


def is_usable_vision_description(text: str, *, prompt: str = _VISION_DESCRIBE_PROMPT) -> bool:
    """Reject responses that indicate the model never saw the image."""
    cleaned = sanitize_vision_output(text)
    if len(cleaned) < 8:
        return False
    lowered = cleaned.lower()
    if (prompt or "").strip() and (prompt or "").strip() in cleaned:
        return False
    return not any(pattern in lowered for pattern in _UNUSABLE_VISION_PATTERNS)


def _profile_uses_minimax_m2_text_api(profile: Any) -> bool:
    model = str(getattr(profile, "model", "") or "").lower()
    base_url = str(getattr(profile, "base_url", "") or "").lower()
    return model.startswith("minimax-m2") and "minimax" in base_url


def _profile_supports_direct_image_input(profile: Any) -> bool:
    """Best-effort guard: avoid sending images to known text-only chat models."""
    if _profile_uses_minimax_m2_text_api(profile):
        return False
    model = str(getattr(profile, "model", "") or "").lower()
    return any(hint in model for hint in _VISION_CAPABLE_MODEL_HINTS)


def _minimax_vlm_api_key() -> str:
    key = os.getenv("MINIMAX_CN_API_KEY", "").strip()
    if key:
        return key
    base_url = os.getenv("VLM_BASE_URL", "").lower()
    if "minimax" in base_url:
        return os.getenv("VLM_API_KEY", "").strip()
    return ""


def _vision_describe(image_path: str, *, high_accuracy: bool = False) -> str | None:
    """用 LIGHT_VLM_* / VLM_* 多模态模型描述本地图片；失败则降级 mmx CLI。

    OPTIMAL / 默认：先试 light_vision，再回退 vision。
    HIGH_ACCURACY：直接使用 vision（主 VLM）。
    """
    from data_agent.core.llm_profiles import (
        get_llm_profile,
        minimax_vlm_describe_image,
        vision_describe_image,
    )

    roles: tuple[str, ...] = ("vision",) if high_accuracy else ("light_vision", "vision")
    for role in roles:
        profile = get_llm_profile(role)  # type: ignore[arg-type]
        if not profile.is_complete():
            continue
        if _profile_uses_minimax_m2_text_api(profile):
            try:
                result = minimax_vlm_describe_image(profile, image_path, _VISION_DESCRIBE_PROMPT)
                if result and is_usable_vision_description(result):
                    return sanitize_vision_output(result)
                if result:
                    logger.warning(
                        "[LLMEnhancer] MiniMax VLM returned unusable vision description: %s",
                        sanitize_vision_output(result)[:120],
                    )
            except Exception as exc:
                logger.warning("[LLMEnhancer] MiniMax VLM failed: %s", exc)
            continue
        if not _profile_supports_direct_image_input(profile):
            logger.warning(
                "[LLMEnhancer] skip %s model without direct image support: %s",
                role,
                profile.model,
            )
            continue
        try:
            result = vision_describe_image(profile, image_path, _VISION_DESCRIBE_PROMPT)
            if result and is_usable_vision_description(result):
                return sanitize_vision_output(result)
            if result:
                logger.warning(
                    "[LLMEnhancer] %s LLM returned unusable vision description: %s",
                    role,
                    sanitize_vision_output(result)[:120],
                )
        except Exception as exc:
            logger.warning("[LLMEnhancer] %s LLM failed: %s", role, exc)

    if not high_accuracy:
        logger.debug(
            "[LLMEnhancer] light_vision / vision LLM not configured "
            "(need LIGHT_VLM_* or VLM_MODEL_NAME + credentials)"
        )
    else:
        logger.debug(
            "[LLMEnhancer] vision LLM not configured (need VLM_MODEL_NAME + credentials)"
        )
    return _mmx_vision_fallback(image_path)


def _mmx_vision_fallback(image_path: str) -> str | None:
    """降级：用 mmx CLI 做图片描述。"""
    mmx_bin = _mmx_cli_path()
    if not os.path.isfile(mmx_bin):
        logger.debug("[LLMEnhancer] mmx CLI not found at %s", mmx_bin)
        return None
    api_key = _minimax_vlm_api_key()
    if not api_key:
        logger.debug("[LLMEnhancer] mmx vision skipped: MINIMAX_CN_API_KEY / VLM_API_KEY missing")
        return None
    try:
        result = subprocess.run(
            [mmx_bin, "vision", "describe", "--image", image_path,
             "--prompt", _VISION_DESCRIBE_PROMPT, "--region", "cn", "--api-key", api_key],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0 and result.stdout.strip():
            output = sanitize_vision_output(result.stdout)
            if is_usable_vision_description(output):
                return output
            logger.warning("[LLMEnhancer] mmx vision returned unusable description: %s", output[:120])
    except Exception as exc:
        logger.debug("[LLMEnhancer] mmx vision failed: %s", exc)
    return None


def _apply_image_description(block: ParsedDocumentBlock, description: str) -> None:
    desc = sanitize_vision_output(description)
    if not is_usable_vision_description(desc):
        return
    block.vision_description = desc
    if block.caption and desc not in block.caption:
        block.caption = f"{block.caption}\n{desc}"
    elif not block.caption:
        block.caption = desc


def _resolve_figure_image_path(
    block: ParsedDocumentBlock,
    file_path: str,
    file_name: str,
    *,
    tmp_dir: str,
    figure_storage_dir: str | None = None,
) -> str | None:
    """Resolve a local image path for a figure block."""
    from data_agent.parsing.parse_figure_context import figure_output_path
    from data_agent.parsing.parsers.figure_cropper import crop_figure_from_pdf

    image_ref = (block.image_ref or "").strip()
    if image_ref and os.path.isfile(image_ref):
        return image_ref

    storage_base = Path(figure_storage_dir) if figure_storage_dir else None
    persisted = figure_output_path(
        file_name,
        block.block_id,
        base_dir=storage_base,
    )
    if persisted and persisted.is_file():
        return str(persisted)

    if persisted and block.bbox and block.page_hint:
        cropped = crop_figure_from_pdf(
            file_path,
            block.page_hint,
            block.bbox,
            str(persisted),
        )
        if cropped:
            block.image_ref = cropped
            return cropped

    if block.bbox and block.page_hint:
        fallback = os.path.join(tmp_dir, f"{block.block_id}.jpg")
        cropped = crop_figure_from_pdf(
            file_path,
            block.page_hint,
            block.bbox,
            fallback,
        )
        if cropped:
            block.image_ref = cropped
            return cropped

    if image_ref:
        candidate = Path(image_ref)
        if candidate.is_file():
            return str(candidate)
        base = Path(file_path).parent
        joined = base / image_ref
        if joined.is_file():
            return str(joined)

    return None


def _process_figure_block(
    block: ParsedDocumentBlock,
    *,
    image_path: str | None,
    high_accuracy: bool,
) -> tuple[str, bool, bool]:
    """Returns (block_id, vision_used, ocr_skipped)."""
    refs = _IMAGE_MD_RE.findall(block.text or "")
    alt_text = refs[0][0] if refs else ""
    if _mineru_ocr_text(block, alt_text) and block.vision_description:
        return block.block_id, False, True

    if not image_path:
        return block.block_id, False, False

    if _mineru_ocr_text(block, alt_text) and not high_accuracy:
        return block.block_id, False, True

    desc = _vision_describe(image_path, high_accuracy=high_accuracy)
    if desc:
        _apply_image_description(block, desc)
        return block.block_id, True, False

    logger.warning("[LLMEnhancer] all vision methods failed for block %s", block.block_id)
    return block.block_id, False, False


def _prepare_figure_image_paths(
    figure_blocks: list[ParsedDocumentBlock],
    *,
    file_path: str,
    file_name: str,
    tmp_dir: str,
    embedded_images: list[dict],
    figure_storage_dir: str | None = None,
) -> dict[str, str | None]:
    paths: dict[str, str | None] = {}
    embedded_idx = 0
    for block in figure_blocks:
        image_path = _resolve_figure_image_path(
            block,
            file_path,
            file_name,
            tmp_dir=tmp_dir,
            figure_storage_dir=figure_storage_dir,
        )
        if not image_path and embedded_idx < len(embedded_images):
            image_path = embedded_images[embedded_idx]["path"]
            embedded_idx += 1
            block.image_ref = image_path
        paths[block.block_id] = image_path
    return paths


def crop_figure_blocks(
    parsed_doc: ParsedDocument,
    file_path: str,
    *,
    figure_storage_dir: str | None = None,
) -> dict[str, str | None]:
    """Crop/persist figure images without calling VLM."""
    _normalize_figure_blocks(parsed_doc.blocks)
    figure_blocks = [b for b in parsed_doc.blocks if _is_figure_block(b)]
    if not figure_blocks:
        _append_log(parsed_doc, "figure_crop", "ok", "no image blocks")
        return {}

    from data_agent.parsing.parsers.image_extractor import extract_embedded_images

    with tempfile.TemporaryDirectory(prefix="da_figures_") as tmp_dir:
        embedded_images = extract_embedded_images(file_path, parsed_doc.file_name, tmp_dir)
        image_paths = _prepare_figure_image_paths(
            figure_blocks,
            file_path=file_path,
            file_name=parsed_doc.file_name,
            tmp_dir=tmp_dir,
            embedded_images=embedded_images,
            figure_storage_dir=figure_storage_dir,
        )

    cropped = sum(1 for path in image_paths.values() if path)
    _append_log(
        parsed_doc,
        "figure_crop",
        "ok",
        f"cropped={cropped}, embedded={len(embedded_images)}, blocks={len(figure_blocks)}",
    )
    return image_paths


def describe_figure_blocks(
    parsed_doc: ParsedDocument,
    file_path: str,
    *,
    high_accuracy: bool = False,
    max_concurrency: int = 4,
    progress_callback: Callable[[int, int], None] | None = None,
    image_paths: dict[str, str | None] | None = None,
    figure_storage_dir: str | None = None,
) -> None:
    """Describe figure blocks with VLM; persist crops when run storage is bound."""
    _normalize_figure_blocks(parsed_doc.blocks)
    figure_blocks = [b for b in parsed_doc.blocks if _is_figure_block(b)]
    if not figure_blocks:
        _append_log(parsed_doc, "image_desc", "ok", "no image blocks")
        return

    if image_paths is None:
        image_paths = crop_figure_blocks(
            parsed_doc,
            file_path,
            figure_storage_dir=figure_storage_dir,
        )

    vision_used = 0
    ocr_skipped = 0

    total = len(figure_blocks)
    completed = 0

    def _report() -> None:
        nonlocal completed
        completed += 1
        if progress_callback:
            progress_callback(completed, total)

    workers = max(1, min(max_concurrency, total))
    if workers == 1:
        for block in figure_blocks:
            _, used, skipped = _process_figure_block(
                block,
                image_path=image_paths.get(block.block_id),
                high_accuracy=high_accuracy,
            )
            vision_used += int(used)
            ocr_skipped += int(skipped)
            _report()
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [
                pool.submit(
                    _process_figure_block,
                    block,
                    image_path=image_paths.get(block.block_id),
                    high_accuracy=high_accuracy,
                )
                for block in figure_blocks
            ]
            for future in as_completed(futures):
                _, used, skipped = future.result()
                vision_used += int(used)
                ocr_skipped += int(skipped)
                _report()

    _append_log(
        parsed_doc,
        "image_desc",
        "ok",
        (
            f"vision={vision_used}, ocr_kept={ocr_skipped}, "
            f"blocks={len(figure_blocks)}"
        ),
    )


def _describe_images(
    parsed_doc: ParsedDocument,
    file_path: str,
    *,
    enable: bool,
    high_accuracy: bool = False,
) -> None:
    """从原始文件提取嵌入图片，用 mmx vision / LLM vision 生成描述。"""
    if not enable:
        _append_log(parsed_doc, "image_desc", "skipped", "disabled")
        return

    from data_agent.core.config import get_parsing_image_desc_max_concurrency

    describe_figure_blocks(
        parsed_doc,
        file_path,
        high_accuracy=high_accuracy,
        max_concurrency=get_parsing_image_desc_max_concurrency(),
    )


def _apply_chapter_tree(parsed_doc: ParsedDocument) -> None:
    """构建并附加章节树"""
    tree = _build_chapter_tree(parsed_doc.blocks)
    parsed_doc.chapter_tree = tree
    headings = _collect_heading_blocks(parsed_doc.blocks)
    _append_log(parsed_doc, "structure", "ok", f"{len(tree)} root chapters, {len(headings)} headings")


def enhance_parsed_document_sync(
    parsed_doc: ParsedDocument,
    file_path: str,
    *,
    enable_correction: bool = True,
    enable_completion: bool = True,
    enable_formula: bool = True,
    enable_image_desc: bool = False,
    processing_mode: str | None = None,
    **_extra: Any,  # 忽略调用方传入的额外 flags
) -> ParsedDocument:
    """同步增强入口 — 不用 async/await，避免事件循环冲突"""
    # 1. 章节树（不调 LLM）
    _apply_chapter_tree(parsed_doc)

    # 2. OCR 纠错
    _correct_blocks(parsed_doc, enable=enable_correction)

    # 3. 缺失章节推断
    if enable_completion:
        _infer_missing_sections(parsed_doc)

    # 4. 公式 LaTeX 化
    _extract_formulas(parsed_doc, enable=enable_formula)

    # 5. 图片描述
    mode = (processing_mode or "").strip().lower()
    high_accuracy = mode in {"high_accuracy", "deep", "enhanced"}
    _describe_images(parsed_doc, file_path, enable=enable_image_desc, high_accuracy=high_accuracy)

    return parsed_doc
