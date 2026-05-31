"""Invalidate wizard downstream artifacts when upstream inputs change."""

from __future__ import annotations

import json
from typing import Any, Iterable

from data_agent.super_agent.schemas import SuperAgentMaterial, SuperAgentRun

WIZARD_CLASSIFY_COMPLETED_STEPS = frozenset({"classify", "classify_post_bootstrap"})
WIZARD_PARSE_COMPLETED_STEPS = frozenset({"structure_materials"})


def _material_key(material: SuperAgentMaterial | dict[str, Any]) -> tuple:
    if isinstance(material, SuperAgentMaterial):
        data = material.model_dump(mode="json")
    elif isinstance(material, dict):
        data = material
    else:
        data = {}
    return (
        str(data.get("name") or "").strip(),
        int(data.get("file_size") or 0),
        str(data.get("file_id") or "").strip(),
        str(data.get("upload_id") or "").strip(),
        str(data.get("file_path") or "").strip(),
        str(data.get("role") or "").strip(),
    )


def materials_fingerprint(materials: Iterable[SuperAgentMaterial | dict[str, Any]]) -> str:
    keys = sorted(_material_key(item) for item in materials)
    return json.dumps(keys, ensure_ascii=False, separators=(",", ":"))


def materials_changed(
    before: Iterable[SuperAgentMaterial | dict[str, Any]],
    after: Iterable[SuperAgentMaterial | dict[str, Any]],
) -> bool:
    return materials_fingerprint(before) != materials_fingerprint(after)


def invalidate_wizard_from_phase(run: SuperAgentRun, *, from_step: int = 2) -> None:
    """Drop derived wizard state from ``from_step`` onward (2=classify, 3=parse)."""
    remove_steps: set[str] = set()

    if from_step <= 2:
        run.classification = {}
        run.route_decision = None
        run.phase_artifacts.pop("classify_and_route", None)
        remove_steps |= set(WIZARD_CLASSIFY_COMPLETED_STEPS)

    if from_step <= 3:
        run.parse_preview = {}
        bundle = run.structured_bundle
        bundle.parse_artifact = {}
        bundle.document_ir = {}
        bundle.section_tree = {}
        bundle.evidence_pool = {}
        bundle.materials = []
        bundle.parser_traces = []
        run.phase_artifacts.pop("document_parse", None)
        remove_steps |= set(WIZARD_PARSE_COMPLETED_STEPS)

    if remove_steps:
        run.completed_steps = [
            step_id for step_id in run.completed_steps if step_id not in remove_steps
        ]
