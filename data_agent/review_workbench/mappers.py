"""Status / step → unified workbench phase and visible-tab mappers."""

from __future__ import annotations

from data_agent.integrations.satellite_review.gnc_schemas import GNCReviewStatus
from data_agent.review_plus.schemas import ReviewPlusStatus
from data_agent.review_workbench.schemas import WorkbenchPhase, WorkbenchTab

GNC_WORKFLOW_STEPS = [
    "review_intake",
    "document_structuring",
    "quality_screening",
    "evidence_pool_building",
    "knowledge_preparation",
    "committee_review",
    "editorial_synthesis",
    "chief_adjudication",
    "human_arbitration",
    "review_closure",
]

GNC_STEP_LABELS: dict[str, str] = {
    "review_intake": "送审材料接收",
    "document_structuring": "文档结构化",
    "quality_screening": "质量筛查",
    "evidence_pool_building": "证据池构建",
    "knowledge_preparation": "知识准备",
    "committee_review": "委员会审查",
    "editorial_synthesis": "合稿归并",
    "chief_adjudication": "总师审定",
    "human_arbitration": "人工仲裁（按需）",
    "review_closure": "闭环报告",
}

GNC_STEP_TO_TAB: dict[str, WorkbenchTab] = {
    "review_intake": WorkbenchTab.OVERVIEW,
    "document_structuring": WorkbenchTab.EVIDENCES,
    "quality_screening": WorkbenchTab.EVIDENCES,
    "evidence_pool_building": WorkbenchTab.EVIDENCES,
    "knowledge_preparation": WorkbenchTab.EVIDENCES,
    "committee_review": WorkbenchTab.COMMITTEE,
    "editorial_synthesis": WorkbenchTab.RID,
    "chief_adjudication": WorkbenchTab.DECISION,
    "human_arbitration": WorkbenchTab.ARBITRATION,
    "review_closure": WorkbenchTab.OVERVIEW,
}

REVIEW_PLUS_PIPELINE_STEPS = [
    "material_classification",
    "scenario_detection",
    "document_structuring",
    "chief_orchestration",
    "rule_extraction",
    "rule_section_mapping",
    "item_review",
    "traceability",
    "cross_document_review",
    "report_composition",
]

REVIEW_PLUS_STEP_TO_TAB: dict[str, WorkbenchTab] = {
    "material_classification": WorkbenchTab.MATERIALS,
    "scenario_detection": WorkbenchTab.MATERIALS,
    "document_structuring": WorkbenchTab.CHECK_ITEMS,
    "chief_orchestration": WorkbenchTab.CHECK_ITEMS,
    "rule_extraction": WorkbenchTab.CHECK_ITEMS,
    "rule_section_mapping": WorkbenchTab.CHECK_ITEMS,
    "item_review": WorkbenchTab.FINDINGS,
    "traceability": WorkbenchTab.TRACEABILITY,
    "cross_document_review": WorkbenchTab.CROSS_DOC,
    "report_composition": WorkbenchTab.OVERVIEW,
}

REVIEW_PLUS_PRE_REVIEW_STATUSES = {
    ReviewPlusStatus.DRAFT.value,
    ReviewPlusStatus.MATERIALS_UPLOADED.value,
    ReviewPlusStatus.PARSED.value,
    ReviewPlusStatus.CLASSIFIED.value,
    ReviewPlusStatus.SCENARIO_DETECTED.value,
    ReviewPlusStatus.READY.value,
    ReviewPlusStatus.LIMITED_PASS.value,
}

REVIEW_PLUS_RUNNING_STATUSES = {
    ReviewPlusStatus.PARSING.value,
    ReviewPlusStatus.CLASSIFYING.value,
    ReviewPlusStatus.STRUCTURING.value,
    ReviewPlusStatus.RULE_EXTRACTING.value,
    ReviewPlusStatus.MAPPING.value,
    ReviewPlusStatus.REVIEWING.value,
    ReviewPlusStatus.TRACEABILITY_BUILDING.value,
    ReviewPlusStatus.REPORTING.value,
    ReviewPlusStatus.GATEKEEPING.value,
}

REVIEW_PLUS_STEP_COMPLETE_EVENTS = {
    step: f"{step}_completed" for step in REVIEW_PLUS_PIPELINE_STEPS
}


def _normalize_status(status: str | GNCReviewStatus | ReviewPlusStatus) -> str:
    if isinstance(status, (GNCReviewStatus, ReviewPlusStatus)):
        return status.value
    return str(status or "").strip().lower()


def _event_types(events: list[dict] | None) -> set[str]:
    return {str(event.get("type", "")) for event in (events or []) if isinstance(event, dict)}


def _review_plus_review_started(events: list[dict] | None) -> bool:
    event_types = _event_types(events)
    if "review_start_requested" in event_types or "review_continue_requested" in event_types:
        return True
    return any(event_type.endswith("_completed") for event_type in event_types if event_type in REVIEW_PLUS_STEP_COMPLETE_EVENTS.values())


def _review_plus_completed_steps(events: list[dict] | None) -> set[str]:
    event_types = _event_types(events)
    return {step for step, complete_event in REVIEW_PLUS_STEP_COMPLETE_EVENTS.items() if complete_event in event_types}


def map_gnc_status_to_phase(
    status: str | GNCReviewStatus,
    *,
    current_step: str = "",
    completed_steps: set[str] | None = None,
) -> WorkbenchPhase:
    normalized = _normalize_status(status)
    step = str(current_step or "").strip()

    if normalized == GNCReviewStatus.FAILED.value:
        return WorkbenchPhase.FAILED
    if normalized == GNCReviewStatus.COMPLETED.value:
        return WorkbenchPhase.COMPLETED
    if normalized == GNCReviewStatus.ARBITRATION_PENDING.value:
        return WorkbenchPhase.ARBITRATION
    if normalized in {GNCReviewStatus.DRAFT.value, GNCReviewStatus.READY.value}:
        return WorkbenchPhase.PRE_REVIEW
    if normalized == GNCReviewStatus.RUNNING.value:
        if not step or step in {"review_intake", "queued"}:
            return WorkbenchPhase.STARTUP
        if completed_steps is not None and not completed_steps:
            return WorkbenchPhase.STARTUP
        return WorkbenchPhase.EXECUTING
    return WorkbenchPhase.EXECUTING


def map_review_plus_status_to_phase(
    status: str | ReviewPlusStatus,
    *,
    events: list[dict] | None = None,
    completed_steps: set[str] | None = None,
) -> WorkbenchPhase:
    normalized = _normalize_status(status)
    steps = completed_steps if completed_steps is not None else _review_plus_completed_steps(events)

    if normalized == ReviewPlusStatus.COMPLETED.value:
        return WorkbenchPhase.COMPLETED
    if normalized == ReviewPlusStatus.FAILED.value:
        return WorkbenchPhase.FAILED
    if normalized in REVIEW_PLUS_PRE_REVIEW_STATUSES and not _review_plus_review_started(events):
        return WorkbenchPhase.PRE_REVIEW
    if normalized in REVIEW_PLUS_RUNNING_STATUSES and not steps:
        return WorkbenchPhase.STARTUP
    if normalized in REVIEW_PLUS_PRE_REVIEW_STATUSES and _review_plus_review_started(events) and not steps:
        return WorkbenchPhase.STARTUP
    return WorkbenchPhase.EXECUTING


def resolve_gnc_visible_tabs(
    *,
    status: str | GNCReviewStatus,
    current_step: str = "",
    completed_steps: set[str] | None = None,
    requires_arbitration: bool = False,
    report_available: bool = False,
) -> list[str]:
    normalized = _normalize_status(status)
    phase = map_gnc_status_to_phase(
        normalized,
        current_step=current_step,
        completed_steps=completed_steps,
    )
    steps = completed_steps or set()
    visible: set[WorkbenchTab] = {WorkbenchTab.EVENTS}

    if phase == WorkbenchPhase.PRE_REVIEW:
        visible.update({WorkbenchTab.OVERVIEW, WorkbenchTab.MATERIALS, WorkbenchTab.FLOW})
        return sorted(tab.value for tab in visible)

    if phase == WorkbenchPhase.FAILED:
        visible.update({WorkbenchTab.OVERVIEW, WorkbenchTab.FLOW, WorkbenchTab.MATERIALS})
        for step_key in steps:
            tab = GNC_STEP_TO_TAB.get(step_key)
            if tab and tab not in {WorkbenchTab.OVERVIEW}:
                visible.add(tab)
        if report_available:
            visible.add(WorkbenchTab.REPORT)
        return sorted(tab.value for tab in visible)

    if phase in {WorkbenchPhase.STARTUP, WorkbenchPhase.EXECUTING}:
        visible.update({WorkbenchTab.OVERVIEW, WorkbenchTab.FLOW, WorkbenchTab.MATERIALS})
        if current_step:
            tab = GNC_STEP_TO_TAB.get(current_step)
            if tab:
                visible.add(tab)
        for step_key in steps:
            tab = GNC_STEP_TO_TAB.get(step_key)
            if tab:
                visible.add(tab)
        return sorted(tab.value for tab in visible)

    visible.update(
        {
            WorkbenchTab.OVERVIEW,
            WorkbenchTab.FLOW,
            WorkbenchTab.MATERIALS,
            WorkbenchTab.FINDINGS,
            WorkbenchTab.RID,
            WorkbenchTab.MINUTES,
            WorkbenchTab.DECISION,
            WorkbenchTab.COMMITTEE,
            WorkbenchTab.EVIDENCES,
        }
    )
    if requires_arbitration or phase == WorkbenchPhase.ARBITRATION:
        visible.add(WorkbenchTab.ARBITRATION)
    if report_available:
        visible.add(WorkbenchTab.REPORT)
    return sorted(tab.value for tab in visible)


def resolve_review_plus_visible_tabs(
    *,
    status: str | ReviewPlusStatus,
    events: list[dict] | None = None,
    completed_steps: set[str] | None = None,
    has_coverage_artifacts: bool = False,
) -> list[str]:
    normalized = _normalize_status(status)
    steps = completed_steps if completed_steps is not None else _review_plus_completed_steps(events)
    started = _review_plus_review_started(events)
    visible: set[WorkbenchTab] = set()

    if normalized in REVIEW_PLUS_PRE_REVIEW_STATUSES and not started:
        return [WorkbenchTab.MATERIALS.value]

    if normalized == ReviewPlusStatus.COMPLETED.value or started:
        visible.add(WorkbenchTab.OVERVIEW)
        visible.add(WorkbenchTab.FLOW)
        visible.add(WorkbenchTab.MATERIALS)
    if normalized == ReviewPlusStatus.COMPLETED.value:
        visible.add(WorkbenchTab.FINDINGS)

    for step_key in steps:
        tab = REVIEW_PLUS_STEP_TO_TAB.get(step_key)
        if tab and tab not in {WorkbenchTab.FLOW, WorkbenchTab.MATERIALS}:
            visible.add(tab)

    if "item_review" in steps and has_coverage_artifacts:
        visible.add(WorkbenchTab.COVERAGE)

    if normalized == ReviewPlusStatus.FAILED.value and started:
        visible.update({WorkbenchTab.OVERVIEW, WorkbenchTab.EVENTS})

    visible.add(WorkbenchTab.EVENTS)
    return sorted(tab.value for tab in visible)
