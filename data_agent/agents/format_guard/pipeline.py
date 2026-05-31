"""Self-healing structuring pipeline orchestration."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from data_agent.parsing.schemas import DocumentSectionTree, ParsedDocument, ParsedDocumentBlock
from data_agent.parsing.artifact_builder import build_sections
from data_agent.agents.context_resolver.anaphora_resolver import AnaphoraResolverAgent
from data_agent.agents.context_resolver.entity_index import EntityIndex
from data_agent.agents.format_guard.format_detector import FormatDetector
from data_agent.agents.format_guard.mode_policy import ModePolicy, resolve_mode
from data_agent.agents.format_guard.repair_agent import RepairAgent, build_repair_contexts
from data_agent.agents.context_resolver.schemas import AnaphoraRecord
from data_agent.agents.format_guard.schemas import (
    BlockDamageReport,
    HealingStats,
    ProcessingMode,
    RepairRecord,
    StructuredCorpusResult,
)

if TYPE_CHECKING:
    from data_agent.agents.inspector.cost_tracker import CostTrackerProtocol
    from data_agent.agents.inspector.diff_recorder import DiffRecorder

logger = logging.getLogger(__name__)


class SelfHealingPipeline:
    def __init__(
        self,
        *,
        format_detector: FormatDetector | None = None,
        repair_agent: RepairAgent | None = None,
        anaphora_resolver: AnaphoraResolverAgent | None = None,
    ) -> None:
        self._detector = format_detector or FormatDetector()
        self._repair = repair_agent
        self._anaphora = anaphora_resolver

    async def run(
        self,
        document: ParsedDocument,
        *,
        processing_mode: ProcessingMode = "OPTIMAL",
        section_tree: DocumentSectionTree | None = None,
        cost_tracker: CostTrackerProtocol | Any | None = None,
        diff_recorder: DiffRecorder | Any | None = None,
    ) -> StructuredCorpusResult:
        policy = resolve_mode(processing_mode)
        blocks = document.blocks
        warnings: list[str] = list(document.structuring_warnings or [])

        damage_reports = self._detector.detect(blocks)
        self._annotate_damage(blocks, damage_reports)

        repair_records: list[RepairRecord] = []
        repaired_count = 0

        if policy.run_repair_llm and damage_reports:
            repair_agent = self._repair or RepairAgent(
                context_window=policy.context_window,
                cost_tracker=cost_tracker,
            )
            limited_reports = damage_reports[: policy.max_repair_blocks]
            if len(damage_reports) > len(limited_reports):
                warnings.append(
                    f"repair capped at {policy.max_repair_blocks} blocks "
                    f"({len(damage_reports)} damaged)"
                )
            contexts = build_repair_contexts(
                blocks,
                limited_reports,
                context_window=policy.context_window,
            )
            repair_records = await repair_agent.repair_blocks(contexts)
            if diff_recorder is not None:
                diff_recorder.record_repairs(repair_records)
            repaired_count = sum(1 for r in repair_records if r.repair_status == "ok")
            self._apply_repair_metadata(blocks, repair_records)
            post_damage = self._detector.detect(blocks)
            self._annotate_damage(blocks, post_damage)
            damage_reports = post_damage
        elif damage_reports:
            warnings.append(
                f"{len(damage_reports)} damaged blocks detected; LLM repair disabled for mode"
            )

        tree = section_tree or build_sections(document)
        entity_index = EntityIndex.from_section_tree(blocks, tree)

        anaphora_records: list[AnaphoraRecord] = []
        anaphora_count = 0
        if policy.run_anaphora_llm:
            resolver = self._anaphora or AnaphoraResolverAgent()
            anaphora_records = await resolver.resolve_document(
                blocks,
                tree,
                entity_index,
            )
            anaphora_count = sum(1 for r in anaphora_records if r.resolver_status == "ok")
            self._apply_anaphora_metadata(blocks, anaphora_records)

        document.structuring_mode = processing_mode
        document.structuring_warnings = warnings

        stats = HealingStats(
            blocks_total=len(blocks),
            damaged_count=len(
                [b for b in blocks if b.format_damage_types]
            ),
            repaired_count=repaired_count,
            anaphora_resolved_count=anaphora_count,
            warnings=warnings,
        )

        return StructuredCorpusResult(
            document=document,
            section_tree=tree,
            damage_reports=damage_reports,
            repair_records=repair_records,
            anaphora_records=anaphora_records,
            stats=stats,
            processing_mode=processing_mode,
        )

    def run_sync(
        self,
        document: ParsedDocument,
        **kwargs: object,
    ) -> StructuredCorpusResult:
        def _run() -> StructuredCorpusResult:
            return asyncio.run(self.run(document, **kwargs))  # type: ignore[arg-type]

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return _run()

        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(_run).result()

    def _annotate_damage(
        self,
        blocks: list[ParsedDocumentBlock],
        reports: list[BlockDamageReport],
    ) -> None:
        by_id = {r.block_id: r for r in reports}
        for block in blocks:
            report = by_id.get(block.block_id)
            if report:
                block.format_damage_types = [d.value for d in report.damage_types]
            else:
                block.format_damage_types = []

    def _apply_repair_metadata(
        self,
        blocks: list[ParsedDocumentBlock],
        records: list[RepairRecord],
    ) -> None:
        by_id = {b.block_id: b for b in blocks}
        for record in records:
            block = by_id.get(record.block_id)
            if block and record.repair_status == "ok":
                block.self_healed = True

    def _apply_anaphora_metadata(
        self,
        blocks: list[ParsedDocumentBlock],
        records: list[AnaphoraRecord],
    ) -> None:
        by_id = {b.block_id: b for b in blocks}
        for record in records:
            block = by_id.get(record.block_id)
            if block and record.resolver_status == "ok":
                block.self_healed = True
