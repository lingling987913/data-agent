"""Chinese anaphora resolution for parsed document blocks."""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import ClassVar

from data_agent.parsing.schemas import DocumentSectionTree, ParsedDocumentBlock
import data_agent.agents.format_guard.llm_client as llm_client
from data_agent.agents.context_resolver.entity_index import EntityIndex
from data_agent.agents.format_guard.numeric_conservation import check_numeric_conservation
from data_agent.agents.context_resolver.schemas import AnaphoraRecord

logger = logging.getLogger(__name__)
DEFAULT_ANAPHORA_SYSTEM = (
    "你是工程文档指代消解专家。"
    "将「该/此/上述/上表/下图/本方案/前述/该公式」等悬空指代替换为文档中可核验的章节、表格或公式名称。"
    "不得虚构不存在的章节号。不得增删改任何数字、单位、符号、参数名。"
    "只输出改写后的段落正文，不要解释。"
)


class AnaphoraResolverAgent:
    ANAPHORA_RE: ClassVar[re.Pattern[str]] = re.compile(
        r"(该公式|上表|下图|本方案|前述|上述|该表|此表|该图|此图|该节|此节|该方案|"
        r"该算法|此算法|该参数|此参数|该指标|此指标|该值|此值|该|此)"
    )

    def __init__(
        self,
        *,
        model_id: str | None = None,
        system_prompt: str | None = None,
    ) -> None:
        self.model_id = model_id
        self._system_prompt = system_prompt or DEFAULT_ANAPHORA_SYSTEM

    def needs_resolution(self, text: str) -> bool:
        if not text or not text.strip():
            return False
        return bool(self.ANAPHORA_RE.search(text))

    async def resolve_document(
        self,
        blocks: list[ParsedDocumentBlock],
        section_tree: DocumentSectionTree,
        entity_index: EntityIndex,
        *,
        max_blocks: int | None = None,
        max_concurrency: int = 3,
    ) -> list[AnaphoraRecord]:
        targets = [b for b in blocks if self.needs_resolution(b.text or "")]
        if max_blocks is not None:
            targets = targets[:max_blocks]
        if not targets:
            return []

        sem = asyncio.Semaphore(max(1, max_concurrency))

        async def _one(block: ParsedDocumentBlock) -> AnaphoraRecord:
            async with sem:
                return await self.resolve_block(block, entity_index, section_tree)

        return list(await asyncio.gather(*[_one(b) for b in targets]))

    async def resolve_block(
        self,
        block: ParsedDocumentBlock,
        entity_index: EntityIndex,
        section_tree: DocumentSectionTree,
    ) -> AnaphoraRecord:
        text_before = block.text or ""
        if not self.needs_resolution(text_before):
            return AnaphoraRecord(
                block_id=block.block_id,
                text_before=text_before,
                text_after=text_before,
                resolver_status="skipped",
            )

        candidates = entity_index.candidates_for_block(block)
        candidate_labels = [a.label for a in candidates]
        section_path = _section_path_for_block(block, section_tree, entity_index)
        user_prompt = _build_user_prompt(text_before, candidate_labels, section_path)
        model = self.model_id
        started = time.perf_counter()

        try:
            from data_agent.core.config import get_structuring_anaphora_model

            model = model or get_structuring_anaphora_model()
            resolved = await llm_client.complete_text(
                self._system_prompt,
                user_prompt,
                model_id=model,
                temperature=0.0,
                max_tokens=2048,
            )
        except llm_client.StructuringLLMError as exc:
            logger.warning("[AnaphoraResolver] block %s skipped: %s", block.block_id, exc)
            return AnaphoraRecord(
                block_id=block.block_id,
                text_before=text_before,
                text_after=text_before,
                matched_entities=candidate_labels[:5],
                resolver_status="failed",
            )
        except Exception as exc:
            logger.warning("[AnaphoraResolver] block %s failed: %s", block.block_id, exc)
            return AnaphoraRecord(
                block_id=block.block_id,
                text_before=text_before,
                text_after=text_before,
                matched_entities=candidate_labels[:5],
                resolver_status="failed",
            )

        resolved = _strip_fences(resolved)
        if not resolved.strip():
            return AnaphoraRecord(
                block_id=block.block_id,
                text_before=text_before,
                text_after=text_before,
                matched_entities=candidate_labels[:5],
                resolver_status="failed",
            )

        if not check_numeric_conservation(text_before, resolved):
            logger.warning(
                "[AnaphoraResolver] block %s numeric conservation failed",
                block.block_id,
            )
            return AnaphoraRecord(
                block_id=block.block_id,
                text_before=text_before,
                text_after=text_before,
                matched_entities=candidate_labels[:5],
                resolver_status="failed",
            )

        if _length_change_ratio(text_before, resolved) > 0.3:
            logger.warning(
                "[AnaphoraResolver] block %s output length change >30%%, applying with warning",
                block.block_id,
            )

        block.text = resolved
        matched = [label for label in candidate_labels if label in resolved]
        return AnaphoraRecord(
            block_id=block.block_id,
            text_before=text_before,
            text_after=resolved,
            matched_entities=matched or candidate_labels[:3],
            resolver_status="ok",
        )


def _build_user_prompt(text: str, candidates: list[str], section_path: str) -> str:
    cand_lines = "\n".join(f"- {c}" for c in candidates[:12]) or "- （无候选）"
    parts = [
        f"当前章节路径: {section_path or '未知'}",
        "候选实体（从中选择可核验的引用，勿虚构）：",
        cand_lines,
        "=== 待消解段落 ===",
        text,
        "请输出消解后的段落（仅正文）：",
    ]
    return "\n\n".join(parts)


def _section_path_for_block(
    block: ParsedDocumentBlock,
    tree: DocumentSectionTree,
    entity_index: EntityIndex,
) -> str:
    section_id = entity_index._block_section.get(block.block_id)
    if not section_id:
        return ""
    by_id = {s.section_id: s for s in tree.sections}
    parts: list[str] = []
    current = by_id.get(section_id)
    while current is not None:
        label = f"{current.number} {current.title}".strip() if current.number else current.title
        parts.append(label)
        parent_id = current.parent_section_id
        current = by_id.get(parent_id) if parent_id else None
    return " > ".join(reversed(parts))


def _strip_fences(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if len(lines) >= 2 and lines[-1].strip() == "```":
            return "\n".join(lines[1:-1]).strip()
        return "\n".join(lines[1:]).strip()
    return stripped


def _length_change_ratio(before: str, after: str) -> float:
    if not before:
        return 0.0
    return abs(len(after) - len(before)) / len(before)
