"""Wizard phase handler protocol and shared context."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional, Protocol, runtime_checkable

from data_agent.super_agent.execution_plan import ParsingPlan
from data_agent.super_agent.schemas import (
    CreateSuperAgentRunRequest,
    SuperAgentRouteDecision,
    SuperAgentRun,
    SuperAgentSkillTrace,
    SaveWizardCheckpointRequest,
)
from data_agent.super_agent.wizard_phases import PHASE_WIZARD_STEP, advance_wizard_phase

WIZARD_PHASE_IDS = (
    "upload",
    "classify_and_route",
    "document_parse",
    "document_review",
    "review_results",
)


@dataclass
class PhaseContext:
    run: SuperAgentRun
    request: CreateSuperAgentRunRequest | None = None
    resume: bool = False
    decision: SuperAgentRouteDecision | None = None
    plan: ParsingPlan | None = None


@runtime_checkable
class RunHost(Protocol):
    """Infrastructure surface exposed by SuperAgentService to phase handlers."""

    @property
    def phases(self) -> PhaseRegistry: ...

    def get_run(self, run_id: str) -> SuperAgentRun | None: ...
    def checkpoint_run(self, run: SuperAgentRun) -> None: ...
    def mark_step_completed(self, run: SuperAgentRun, step_id: str) -> None: ...
    def step_completed(self, run: SuperAgentRun, step_id: str) -> bool: ...
    def latest_skill_trace(self, run: SuperAgentRun, skill_id: str) -> SuperAgentSkillTrace | None: ...
    def run_with_periodic_checkpoints(
        self,
        run: SuperAgentRun,
        task_fn: Callable[[], Any],
        *,
        interval_seconds: float = 60,
    ) -> Any: ...
    def structure_phase_complete(self, run: SuperAgentRun) -> bool: ...
    def parse_phase_complete(self, run: SuperAgentRun, plan: ParsingPlan) -> bool: ...


@runtime_checkable
class WizardPhaseHandler(Protocol):
    phase_id: str
    wizard_step: int

    def apply_wizard_checkpoint(self, run: SuperAgentRun, req: SaveWizardCheckpointRequest) -> None: ...


class PhaseHandlerBase:
    phase_id: str = ""
    wizard_step: int = 0

    def __init__(self, host: RunHost) -> None:
        self._host = host

    def apply_wizard_checkpoint(self, run: SuperAgentRun, req: SaveWizardCheckpointRequest) -> None:
        return None


@dataclass
class PhaseRegistry:
    upload: Any
    classify_and_route: Any
    document_parse: Any
    document_review: Any
    review_results: Any

    def by_id(self, phase_id: str) -> WizardPhaseHandler:
        handler = getattr(self, phase_id, None)
        if handler is None:
            raise KeyError(f"Unknown wizard phase: {phase_id}")
        return handler
