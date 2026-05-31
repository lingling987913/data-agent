"""姿态控制 (AC) 专业组子工作流 — 最小等价骨架，复用 run_unit_review / execute_unit_rules。"""

from __future__ import annotations

from typing import Any

from data_agent.integrations.satellite_review.review_template_service import (
    get_stage_contract_rules,
    resolve_template,
)
from data_agent.integrations.satellite_review.workflows.group_review_common import (
    run_group_review_pipeline,
)

_AC_STAGE_UNITS: list[tuple[str, str]] = [
    ("req_err", "ac_requirement_error_unit"),
    ("thruster_layout", "ac_thruster_layout_unit"),
    ("other_actuator_layout", "ac_actuator_layout_unit"),
    ("control_law", "ac_control_law_unit"),
    ("control_params", "ac_control_param_unit"),
    ("maneuver_law", "ac_maneuver_control_unit"),
    ("unloading_law", "ac_momentum_unload_unit"),
    ("simulation", "ac_control_simulation_unit"),
    ("consistency", "ac_cross_consistency_unit"),
    ("report", "ac_report_completeness_unit"),
]

_AC_STAGE_BY_KEY = dict(_AC_STAGE_UNITS)


def _resolve_enabled_ac_stages(
    intake_data: dict,
    unit_evidence_bundles: list | None,
    *,
    selected_units: list | None = None,
) -> set[str]:
    """仅启用模板已配置且当前有文本集/规则配置的 AC 环节（源语义简化版）。"""
    bundle_keys = {
        str(item.get("unit_key") or "")
        for item in (unit_evidence_bundles or [])
        if isinstance(item, dict) and item.get("unit_key")
    }
    selected_ids = {
        str(item.get("unit_id") or "")
        for item in (selected_units or intake_data.get("selected_units") or [])
        if isinstance(item, dict) and item.get("unit_id")
    }
    subsystem = str(intake_data.get("subsystem") or "GNC")
    review_phase = str(intake_data.get("review_phase") or "CDR")
    template_info = intake_data.get("template") or {}
    template_id = str(template_info.get("template_id") or template_info.get("id") or "")
    metadata = intake_data.get("metadata") if isinstance(intake_data.get("metadata"), dict) else {}
    if not template_id:
        template_id = str(metadata.get("template_id") or metadata.get("review_template_id") or "")

    template = resolve_template(subsystem, review_phase, template_id=template_id) if template_id else None
    enabled: set[str] = set()
    for stage_key, unit_id in _AC_STAGE_UNITS:
        registry_id = unit_id
        short_key = unit_id.replace("_unit", "")
        if unit_id in selected_ids:
            enabled.add(stage_key)
            continue
        if stage_key in {"consistency", "report"}:
            enabled.add(stage_key)
            continue
        has_rules = False
        if template:
            ac_review = template.get("ac_review") or {}
            if get_stage_contract_rules(ac_review, stage_key):
                has_rules = True
            elif (ac_review.get("stage_rule_specs") or {}).get(stage_key):
                has_rules = True
        if has_rules or registry_id in bundle_keys or short_key in bundle_keys:
            enabled.add(stage_key)
    return enabled


def _build_ac_stage_plan(enabled_stages: set[str]) -> list[tuple[list[tuple[str, str, list[str] | None]], int]]:
    """源 AC 子工作流 DAG 编排（跳过未启用环节）。"""
    def _item(stage_key: str) -> tuple[str, str, list[str] | None] | None:
        if stage_key not in enabled_stages:
            return None
        unit_id = _AC_STAGE_BY_KEY[stage_key]
        return (stage_key, unit_id, None)

    phases: list[tuple[list[tuple[str, str, list[str] | None]], int]] = []
    first = _item("req_err")
    if first:
        phases.append(([first], 1))

    parallel_layout = [_item("thruster_layout"), _item("other_actuator_layout")]
    parallel_layout = [item for item in parallel_layout if item]
    if parallel_layout:
        phases.append((parallel_layout, 2))

    for stage_key in ("control_law", "control_params"):
        item = _item(stage_key)
        if item:
            phases.append(([item], 1))

    parallel_laws = [_item("maneuver_law"), _item("unloading_law")]
    parallel_laws = [item for item in parallel_laws if item]
    if parallel_laws:
        phases.append((parallel_laws, 2))

    sim = _item("simulation")
    if sim:
        phases.append(([sim], 1))

    for stage_key in ("consistency", "report"):
        item = _item(stage_key)
        if item:
            phases.append(([item], 1))

    return phases


def _build_knowledge_data(
    intake_data: dict[str, Any],
    *,
    struct_data: dict[str, Any] | None,
    unit_evidence_bundles: list | None,
    evidences: list,
    review_rules: list | None = None,
) -> dict[str, Any]:
    quality_data = {
        "intake_data": intake_data,
        "struct_data": struct_data or {},
        "selected_units": intake_data.get("selected_units") or [],
        "template_gatekeeping": intake_data.get("template_gatekeeping") or [],
        "blocked_units": intake_data.get("blocked_units") or [],
    }
    return {
        "quality_data": quality_data,
        "evidences": evidences,
        "review_rules": review_rules or intake_data.get("review_rules") or [],
        "unit_evidence_bundles": unit_evidence_bundles or intake_data.get("unit_evidence_bundles") or [],
    }


def run_ac_review_pipeline(
    intake_data: dict,
    evidences: list,
    document_text: str,
    model_id: str,
    struct_data: dict | None = None,
    unit_evidence_bundles: list | None = None,
    *,
    knowledge_data: dict[str, Any] | None = None,
    evidence_map: dict[str, dict[str, Any]] | None = None,
    debug_mode: bool = False,
) -> tuple[list[dict], dict]:
    """AC 专业组子工作流入口，返回 (findings, conclusion_dict)。"""
    del document_text

    bundles = unit_evidence_bundles or (knowledge_data or {}).get("unit_evidence_bundles")
    quality_data = (knowledge_data or {}).get("quality_data") or {}
    selected_units = quality_data.get("selected_units") or intake_data.get("selected_units")
    enabled_stages = _resolve_enabled_ac_stages(
        intake_data,
        bundles,
        selected_units=selected_units,
    )
    stage_plan = _build_ac_stage_plan(enabled_stages)

    data = knowledge_data or _build_knowledge_data(
        intake_data,
        struct_data=struct_data,
        unit_evidence_bundles=unit_evidence_bundles,
        evidences=evidences,
    )
    ev_map = evidence_map or {
        str(ev.get("evidence_id") or ""): ev for ev in evidences if isinstance(ev, dict) and ev.get("evidence_id")
    }

    findings, _group_review, native_result, _unit_results = run_group_review_pipeline(
        group="ac",
        group_label="姿态控制专业组",
        stage_plan=stage_plan,
        knowledge_data=data,
        evidence_map=ev_map,
        model_id=model_id,
        debug_mode=debug_mode,
    )
    conclusion = native_result["conclusion"]
    conclusion["enabled_stages"] = sorted(enabled_stages)
    conclusion["skipped_stages"] = [
        stage_key for stage_key, _ in _AC_STAGE_UNITS if stage_key not in enabled_stages
    ]
    return findings, conclusion
