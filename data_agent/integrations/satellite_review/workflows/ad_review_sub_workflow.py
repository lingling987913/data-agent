"""姿态确定 (AD) 专业组子工作流 — 最小等价骨架，复用 run_unit_review / execute_unit_rules。"""

from __future__ import annotations

from typing import Any

from data_agent.integrations.satellite_review.workflows.group_review_common import (
    run_group_review_pipeline,
)

# stage_key -> registry unit_id（与源 _AD_STAGE_TO_UNIT_KEY 语义对齐，映射到 data-agent 注册表）
_AD_STAGE_UNITS: list[tuple[str, str]] = [
    ("req_err", "ad_requirement_error_unit"),
    ("timing", "ad_sampling_timing_unit"),
    ("install", "ad_mounting_pointing_unit"),
    ("algorithm", "ad_determination_algorithm_unit"),
    ("simulation", "ad_simulation_analysis_unit"),
    ("consistency", "ad_cross_consistency_unit"),
    ("report", "ad_report_completeness_unit"),
]

# 源 AD 子工作流阶段编排：req_err → (timing ∥ install) → algorithm → simulation → 收口
_AD_STAGE_PLAN: list[tuple[list[tuple[str, str, list[str] | None]], int]] = [
    ([(_AD_STAGE_UNITS[0][0], _AD_STAGE_UNITS[0][1], None)], 1),
    ([(_AD_STAGE_UNITS[1][0], _AD_STAGE_UNITS[1][1], None), (_AD_STAGE_UNITS[2][0], _AD_STAGE_UNITS[2][1], None)], 2),
    ([(_AD_STAGE_UNITS[3][0], _AD_STAGE_UNITS[3][1], None)], 1),
    ([(_AD_STAGE_UNITS[4][0], _AD_STAGE_UNITS[4][1], None)], 1),
    ([(_AD_STAGE_UNITS[5][0], _AD_STAGE_UNITS[5][1], None)], 1),
    ([(_AD_STAGE_UNITS[6][0], _AD_STAGE_UNITS[6][1], None)], 1),
]


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


def run_ad_review_pipeline(
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
    """AD 专业组子工作流入口，返回 (findings, conclusion_dict)。"""
    del document_text  # 由 unit_evidence_bundles 提供证据，不再截断全文

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
        group="ad",
        group_label="姿态确定专业组",
        stage_plan=_AD_STAGE_PLAN,
        knowledge_data=data,
        evidence_map=ev_map,
        model_id=model_id,
        debug_mode=debug_mode,
    )
    return findings, native_result["conclusion"]
