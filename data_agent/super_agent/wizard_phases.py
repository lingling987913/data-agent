"""Wizard phase constants and phase-state helpers (no phase handler imports)."""

from __future__ import annotations

from typing import Any

from data_agent.super_agent.schemas import SuperAgentRun

PHASE_WIZARD_STEP: dict[str, int] = {
    "upload": 1,
    "classify_and_route": 2,
    "document_parse": 3,
    "document_review": 4,
    "review_results": 5,
}

WIZARD_STEP_PHASE: dict[int, str] = {step: phase for phase, step in PHASE_WIZARD_STEP.items()}


def advance_wizard_phase(
    run: SuperAgentRun,
    phase_id: str,
    *,
    status: str = "completed",
    artifact: dict[str, Any] | None = None,
) -> None:
    """Sync semantic phase state with legacy wizard_step (backward compatible)."""
    step = PHASE_WIZARD_STEP.get(phase_id, run.wizard_step)
    run.current_phase = phase_id
    run.phase_status = status
    run.wizard_step = max(run.wizard_step, step)
    if artifact:
        run.phase_artifacts[phase_id] = artifact
