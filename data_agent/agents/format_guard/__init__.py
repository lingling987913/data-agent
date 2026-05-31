"""Format detection and repair (FormatGuard)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from data_agent.agents.format_guard.format_detector import FormatDetector
from data_agent.agents.format_guard.repair_agent import RepairAgent, RepairContext
from data_agent.agents.format_guard.schemas import (
    BlockDamageReport,
    FormatDamageType,
    HealingStats,
    ProcessingMode,
    RepairRecord,
    StructuredCorpusResult,
)

if TYPE_CHECKING:
    from data_agent.agents.format_guard.pipeline import SelfHealingPipeline

__all__ = [
    "BlockDamageReport",
    "FormatDamageType",
    "FormatDetector",
    "HealingStats",
    "ProcessingMode",
    "RepairAgent",
    "RepairContext",
    "RepairRecord",
    "SelfHealingPipeline",
    "StructuredCorpusResult",
]


def __getattr__(name: str) -> object:
    if name == "SelfHealingPipeline":
        from data_agent.agents.format_guard.pipeline import SelfHealingPipeline

        return SelfHealingPipeline
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
