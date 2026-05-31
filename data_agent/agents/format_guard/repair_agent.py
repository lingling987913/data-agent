"""LLM-based format repair for damaged document blocks."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from data_agent.parsing.schemas import ParsedDocumentBlock
from data_agent.agents.format_guard.format_detector import FormatDetector
from data_agent.agents.format_guard import llm_client
from data_agent.agents.format_guard.numeric_conservation import check_numeric_conservation
from data_agent.agents.format_guard.schemas import BlockDamageReport, FormatDamageType, RepairRecord

if TYPE_CHECKING:
    from data_agent.agents.inspector.cost_tracker import CostTrackerProtocol

logger = logging.getLogger(__name__)

_DEFAULT_CONTEXT_WINDOW = 2
DEFAULT_REPAIR_SYSTEM = (
    "你是工程文档 Markdown 语法修复专家。"
    "只修复 HTML 表格标签（table/tr/td/th）闭合问题，以及 LaTeX $ / $$ 定界符配对问题。"
    "禁止改写专业含义。禁止增删改任何数字、单位、符号、参数名。"
    "只输出修复后的 Markdown 片段正文，不要解释，不要代码围栏。"
)


@dataclass
class RepairContext:
    block: ParsedDocumentBlock
    before_blocks: list[ParsedDocumentBlock]
    after_blocks: list[ParsedDocumentBlock]
    damage_types: list[FormatDamageType]


def block_repair_text(block: ParsedDocumentBlock) -> str:
    parts: list[str] = []
    if block.text:
        parts.append(block.text)
    if block.table_markdown:
        parts.append(block.table_markdown)
    if block.formula_latex:
        parts.append(block.formula_latex)
    return "\n\n".join(parts)


def apply_repair_text(block: ParsedDocumentBlock, repaired: str) -> None:
    """Apply repaired content to the primary content field(s)."""
    if block.table_markdown and not block.text:
        block.table_markdown = repaired
    elif block.formula_latex and not block.text and not block.table_markdown:
        block.formula_latex = repaired
    else:
        block.text = repaired


def build_repair_contexts(
    blocks: list[ParsedDocumentBlock],
    reports: list[BlockDamageReport],
    *,
    context_window: int = _DEFAULT_CONTEXT_WINDOW,
) -> list[RepairContext]:
    by_id = {b.block_id: b for b in blocks}
    ordered = sorted(blocks, key=lambda b: b.order_index)
    index_by_id = {b.block_id: i for i, b in enumerate(ordered)}
    contexts: list[RepairContext] = []

    for report in reports:
        block = by_id.get(report.block_id)
        if block is None:
            continue
        idx = index_by_id.get(block.block_id, 0)
        before = ordered[max(0, idx - context_window) : idx]
        after = ordered[idx + 1 : idx + 1 + context_window]
        contexts.append(
            RepairContext(
                block=block,
                before_blocks=before,
                after_blocks=after,
                damage_types=list(report.damage_types),
            )
        )
    return contexts


class RepairAgent:
    def __init__(
        self,
        *,
        model_id: str | None = None,
        context_window: int = _DEFAULT_CONTEXT_WINDOW,
        format_detector: FormatDetector | None = None,
        cost_tracker: CostTrackerProtocol | Any | None = None,
        system_prompt: str | None = None,
    ) -> None:
        self.model_id = model_id
        self.context_window = context_window
        self._detector = format_detector or FormatDetector()
        self._cost_tracker = cost_tracker
        self._system_prompt = system_prompt or DEFAULT_REPAIR_SYSTEM

    async def repair_blocks(
        self,
        contexts: list[RepairContext],
        *,
        max_concurrency: int = 3,
    ) -> list[RepairRecord]:
        if not contexts:
            return []
        sem = asyncio.Semaphore(max(1, max_concurrency))

        async def _one(ctx: RepairContext) -> RepairRecord:
            async with sem:
                return await self.repair_one(ctx)

        return list(await asyncio.gather(*[_one(ctx) for ctx in contexts]))

    async def repair_one(self, ctx: RepairContext) -> RepairRecord:
        block = ctx.block
        text_before = block_repair_text(block)
        damage_labels = [d.value for d in ctx.damage_types]
        started = time.perf_counter()

        if not text_before.strip():
            return RepairRecord(
                block_id=block.block_id,
                damage_types=ctx.damage_types,
                text_before=text_before,
                text_after=text_before,
                repair_status="skipped",
            )

        user_prompt = _build_user_prompt(ctx, text_before)
        model = self.model_id
        try:
            from data_agent.core.config import get_structuring_repair_model

            model = model or get_structuring_repair_model()
            repaired_raw = await llm_client.complete_text(
                self._system_prompt,
                user_prompt,
                model_id=model,
                temperature=0.0,
                max_tokens=4096,
            )
        except llm_client.StructuringLLMError as exc:
            latency_ms = int((time.perf_counter() - started) * 1000)
            self._record_llm_call(
                model or "",
                latency_ms,
                status="failed",
            )
            logger.warning("[RepairAgent] block %s LLM unavailable: %s", block.block_id, exc)
            return RepairRecord(
                block_id=block.block_id,
                damage_types=ctx.damage_types,
                text_before=text_before,
                text_after=text_before,
                repair_status="failed",
                model_id=model or "",
                latency_ms=latency_ms,
            )
        except Exception as exc:
            latency_ms = int((time.perf_counter() - started) * 1000)
            self._record_llm_call(
                model or "",
                latency_ms,
                status="failed",
            )
            logger.warning("[RepairAgent] block %s repair failed: %s", block.block_id, exc)
            return RepairRecord(
                block_id=block.block_id,
                damage_types=ctx.damage_types,
                text_before=text_before,
                text_after=text_before,
                repair_status="failed",
                model_id=model or "",
                latency_ms=latency_ms,
            )

        repaired = _strip_fences(repaired_raw)
        token_estimate = llm_client.estimate_tokens(user_prompt + repaired_raw)
        latency_ms = int((time.perf_counter() - started) * 1000)
        prompt_tokens = llm_client.estimate_tokens(user_prompt)
        completion_tokens = max(0, token_estimate - prompt_tokens)
        remaining = self._detector.detect_text(repaired)
        if remaining:
            logger.info(
                "[RepairAgent] block %s still damaged after repair: %s",
                block.block_id,
                [d.value for d in remaining],
            )
            self._record_llm_call(
                model or "",
                latency_ms,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=token_estimate,
                status="failed",
            )
            return RepairRecord(
                block_id=block.block_id,
                damage_types=ctx.damage_types,
                text_before=text_before,
                text_after=text_before,
                repair_status="failed",
                model_id=model or "",
                latency_ms=latency_ms,
                token_estimate=token_estimate,
            )

        if not check_numeric_conservation(text_before, repaired):
            logger.warning(
                "[RepairAgent] block %s numeric conservation failed",
                block.block_id,
            )
            self._record_llm_call(
                model or "",
                latency_ms,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=token_estimate,
                status="failed",
            )
            return RepairRecord(
                block_id=block.block_id,
                damage_types=ctx.damage_types,
                text_before=text_before,
                text_after=text_before,
                repair_status="failed",
                model_id=model or "",
                latency_ms=latency_ms,
                token_estimate=token_estimate,
            )

        apply_repair_text(block, repaired)
        self._record_llm_call(
            model or "",
            latency_ms,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=token_estimate,
            status="ok",
        )
        return RepairRecord(
            block_id=block.block_id,
            damage_types=ctx.damage_types,
            text_before=text_before,
            text_after=repaired,
            repair_status="ok",
            model_id=model or "",
            latency_ms=latency_ms,
            token_estimate=token_estimate,
        )

    def _record_llm_call(
        self,
        model_id: str,
        latency_ms: int,
        *,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        total_tokens: int = 0,
        status: str = "ok",
    ) -> None:
        if self._cost_tracker is None:
            return
        self._cost_tracker.record_call(
            "repair_agent",
            model_id,
            latency_ms,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            status=status,
        )


def _build_user_prompt(ctx: RepairContext, target_text: str) -> str:
    damage_str = ", ".join(d.value for d in ctx.damage_types)
    before_parts = [
        f"[前文 {b.order_index}] {block_repair_text(b)[:400]}"
        for b in ctx.before_blocks
    ]
    after_parts = [
        f"[后文 {b.order_index}] {block_repair_text(b)[:400]}"
        for b in ctx.after_blocks
    ]
    sections = [
        f"检测到格式损坏类型: {damage_str}",
        "要求：仅修复 HTML/LaTeX 闭合；不得增删改数字、单位、符号、参数名。",
    ]
    if before_parts:
        sections.append("=== 前文上下文 ===\n" + "\n".join(before_parts))
    sections.append("=== 待修复片段 ===\n" + target_text)
    if after_parts:
        sections.append("=== 后文上下文 ===\n" + "\n".join(after_parts))
    sections.append("请输出修复后的片段（仅正文，无解释）：")
    return "\n\n".join(sections)


def _strip_fences(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if len(lines) >= 2 and lines[-1].strip() == "```":
            return "\n".join(lines[1:-1]).strip()
        if lines[0].startswith("```"):
            return "\n".join(lines[1:]).strip()
    return stripped
