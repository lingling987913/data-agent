"""Record self-healing repairs as unified diffs for evaluation traces."""

from __future__ import annotations

import difflib

from data_agent.agents.inspector.schemas import SelfHealingRecord
from data_agent.agents.format_guard.schemas import RepairRecord


class DiffRecorder:
    """Convert repair records into :class:`SelfHealingRecord` with unified diffs."""

    def record_repairs(self, repair_records: list[RepairRecord]) -> list[SelfHealingRecord]:
        out: list[SelfHealingRecord] = []
        for record in repair_records:
            unified_diff = ""
            if record.repair_status == "ok":
                before_lines = record.text_before.splitlines(keepends=True)
                after_lines = record.text_after.splitlines(keepends=True)
                if not before_lines and record.text_before:
                    before_lines = [record.text_before]
                if not after_lines and record.text_after:
                    after_lines = [record.text_after]
                diff_lines = difflib.unified_diff(
                    before_lines,
                    after_lines,
                    fromfile=f"{record.block_id}/before",
                    tofile=f"{record.block_id}/after",
                    lineterm="",
                )
                unified_diff = "\n".join(diff_lines)
            out.append(
                SelfHealingRecord(
                    block_id=record.block_id,
                    damage_types=list(record.damage_types),
                    repair_status=record.repair_status,
                    unified_diff=unified_diff,
                    text_before_len=len(record.text_before),
                    text_after_len=len(record.text_after),
                )
            )
        return out
