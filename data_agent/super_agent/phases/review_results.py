"""Wizard phase: review_results."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from pathlib import Path
from typing import Any, TYPE_CHECKING

from data_agent.core.config import GNC_RUNS_DIR
from data_agent.super_agent import helpers
from data_agent.super_agent.phases.base import PhaseHandlerBase, advance_wizard_phase
from data_agent.super_agent.schemas import (
    CreateSuperAgentRunRequest,
    StructuredReviewBundle,
    SuperAgentInputMode,
    SuperAgentMaterial,
    SuperAgentQualityReport,
    SuperAgentReviewMode,
    SuperAgentRoute,
    SuperAgentRouteDecision,
    SuperAgentRun,
    SuperAgentSkillTrace,
    SuperAgentTraceReport,
)
from data_agent.super_agent.diagnostics_sanitizer import (
    is_internal_diagnostic_text,
    sanitize_business_lines,
    sanitize_report_markdown,
)
from data_agent.super_agent.smart_diagnostics import (
    format_citation_coverage_warning,
    format_committee_limited_note,
    format_committee_limited_warning,
)

if TYPE_CHECKING:
    from data_agent.super_agent.execution_plan import ParsingPlan

logger = logging.getLogger(__name__)


def build_super_agent_user_report(run: SuperAgentRun):
    """Build a CASA/QJ user-facing report without internal trace identifiers."""
    from data_agent.reporting import ReviewReportInput, build_review_report
    from data_agent.review_workbench.super_agent_workbench_service import build_workbench_detail
    from data_agent.review_workbench.workbench_report_snapshot import detail_to_report_snapshot

    route = run.route_decision.route.value if run.route_decision else run.requested_route.value
    review_type = "hybrid" if run.review_plus_result and run.gnc_review_result else (
        "review_plus" if run.review_plus_result else "gnc_review" if run.gnc_review_result else "super_agent"
    )
    objective = run.objective or run.name or ""
    workbench_detail = build_workbench_detail(run)
    workbench_overview = detail_to_report_snapshot(workbench_detail)
    return build_review_report(
        ReviewReportInput(
            report_id=f"super-agent-{run.run_id}",
            review_type=review_type,
            audience="user",
            structured_bundle=run.structured_bundle.model_dump(mode="json"),
            review_results={
                "review_plus_result": run.review_plus_result,
                "gnc_review_result": run.gnc_review_result,
            },
            quality_report=run.quality_report.model_dump(mode="json"),
            metadata={
                "title": "GNC 设计文档审查报告",
                "review_id": run.run_id,
                "review_plus_id": run.source_review_id if route in {"review_plus", "hybrid"} else "",
                "gnc_review_id": (run.route_decision.gnc_review_id if run.route_decision else ""),
                "objective": objective,
                "verdict": workbench_detail.summary.verdict,
                "rationale": workbench_detail.summary.rationale,
                "workbench_overview": workbench_overview,
            },
        )
    )


class ReviewResultsPhaseHandler(PhaseHandlerBase):
    phase_id = "review_results"
    wizard_step = 5

    def __init__(self, host):
        super().__init__(host)

    def execute_pipeline(self, ctx) -> None:
        from data_agent.core.task_board import enrich_smart_committee_result
        from data_agent.evaluation.execution_metrics import build_execution_metrics_snapshot
        from data_agent.super_agent.schemas import SuperAgentStatus

        run = ctx.run
        run.review_plus_result = enrich_smart_committee_result(
            run.review_plus_result,
            classification=run.classification if isinstance(run.classification, dict) else {},
            phase_artifacts=run.phase_artifacts if isinstance(run.phase_artifacts, dict) else {},
        )
        run.trace_report = self.collect_traces(run)
        run.quality_report = self.evaluate_quality(run)
        run.execution_metrics_snapshot = build_execution_metrics_snapshot(super_agent_run=run)
        self.build_report(run)
        run.status = (
            SuperAgentStatus.LIMITED
            if run.quality_report.human_confirmation_required
            or run.trace_report.degradation_summary
            or (
                run.review_plus_result.get("review_mode") == "smart_committee"
                and run.review_plus_result.get("limited")
            )
            else SuperAgentStatus.COMPLETED
        )
        if (
            run.review_plus_result.get("review_mode") == "smart_committee"
            and run.review_plus_result.get("limited")
        ):
            run.review_plus_result["status"] = "limited"
        advance_wizard_phase(
            run,
            "review_results",
            status="completed",
            artifact={
                "status": run.status.value,
                "quality_score": run.quality_report.overall_score,
            },
        )
        self._host.checkpoint_run(run)

    def build_report(self, run: SuperAgentRun) -> dict[str, Any]:
        artifact = build_super_agent_user_report(run)
        run.report_markdown = sanitize_report_markdown(artifact.markdown)
        run.report_artifact = artifact.model_dump(mode="json")
        if isinstance(run.report_artifact.get("markdown"), str):
            run.report_artifact["markdown"] = run.report_markdown
        return run.report_artifact

    def collect_traces(self, run: SuperAgentRun) -> SuperAgentTraceReport:
        report = SuperAgentTraceReport(parser_traces=list(run.structured_bundle.parser_traces))
        if run.source_review_id and (
            run.input_mode == SuperAgentInputMode.EXISTING_REVIEW_PLUS
            or (
                run.route_decision
                and run.route_decision.route
                in {
                    SuperAgentRoute.REVIEW_PLUS,
                    SuperAgentRoute.HYBRID,
                    SuperAgentRoute.STRUCTURE_ONLY,
                }
            )
        ):
            try:
                from data_agent.review_plus.service import get_review_plus_service

                task = get_review_plus_service().get_review(run.source_review_id)
                if task:
                    report.parser_traces = list(task.parser_traces or report.parser_traces)
                    report.agent_run_traces = list(task.agent_run_traces or [])
                    report.workflow_events = list(task.events or [])
                    report.fallback_events = [
                        event
                        for event in task.events or []
                        if "failed_warning" in str(event.get("type", ""))
                        or "skipped" in str(event.get("type", ""))
                    ]
                    if task.status == "failed":
                        report.failed_steps.append({"source": "review_plus", "status": task.status})
            except Exception as exc:
                report.degradation_summary.append(f"Review-Plus trace 汇总失败: {exc}")
        for skill_trace in run.skill_traces:
            if skill_trace.status in {"failed", "skipped"}:
                report.degradation_summary.extend(
                    sanitize_business_lines(skill_trace.warnings or [])
                )
            if skill_trace.skill_id == "smart_review_committee" and isinstance(skill_trace.output_summary, dict):
                output = skill_trace.output_summary
                if output.get("limited"):
                    note = format_committee_limited_note()
                    if note not in report.degradation_summary:
                        report.degradation_summary.append(note)
        review_plus_result = run.review_plus_result or {}
        if review_plus_result.get("review_mode") == "smart_committee":
            if review_plus_result.get("limited"):
                note = format_committee_limited_note()
                if note not in report.degradation_summary:
                    report.degradation_summary.append(note)
        if run.gnc_review_result:
            report.workflow_events.append(
                {
                    "source": "gnc_review",
                    "status": run.gnc_review_result.get("status", ""),
                    "review_mode": run.gnc_review_result.get("review_mode", run.review_mode.value),
                    "gnc_review_id": run.gnc_review_result.get("gnc_review_id")
                    or run.gnc_review_result.get("review_id")
                    or "",
                }
            )
            report.agent_run_traces.extend(run.gnc_review_result.get("traces") or [])
            report.fallback_events.extend(run.gnc_review_result.get("fallback_events") or [])
            if run.gnc_review_result.get("status") == "failed":
                report.failed_steps.append({"source": "gnc_review", "status": "failed"})
        return report

    def evaluate_quality(self, run: SuperAgentRun) -> SuperAgentQualityReport:
        from data_agent.evaluation.super_agent_adapter import score_super_agent_quality

        stats = run.structured_bundle.stats
        material_count = int(stats.get("material_count") or len(run.structured_bundle.materials) or 0)
        evidence_count = int(
            stats.get("evidence_count")
            or len((run.structured_bundle.evidence_pool or {}).get("evidences", []))
            or 0
        )
        trace_summary = run.review_plus_result.get("traceability_summary") or {}
        verification_coverage = float(trace_summary.get("verification_coverage") or 0.0)
        design_coverage = float(trace_summary.get("design_closure_coverage") or 0.0)
        gnc_quality = (
            run.gnc_review_result.get("quality")
            or run.gnc_review_result.get("quality_report")
            or run.gnc_review_result.get("quality_scores")
            or {}
        )
        conflicts = run.gnc_review_result.get("conflicts") or run.gnc_review_result.get("cross_document_conflicts") or []
        committee_failures = (
            (run.gnc_review_result.get("metadata") or {}).get("committee_failures")
            or run.gnc_review_result.get("committee_failures")
            or {}
        )
        gnc_failure_warnings = [
            f"GNC 专家降级: {agent_key}: {error}"
            for agent_key, error in committee_failures.items()
        ]
        expert_consensus = float(
            gnc_quality.get("expert_consensus_score")
            or gnc_quality.get("expert_consistency_score")
            or gnc_quality.get("consensus_score")
            or (1.0 if run.gnc_review_result.get("status") == "completed" else 0.0)
        )
        evidence_sufficiency = float(
            gnc_quality.get("evidence_sufficiency_score")
            or gnc_quality.get("evidence_score")
            or (min(1.0, evidence_count / max(material_count, 1)) if run.gnc_review_result else 0.0)
        )
        conflict_detection = float(
            gnc_quality.get("conflict_detection_score")
            or (1.0 if run.gnc_review_result and not conflicts else 0.65 if conflicts else 0.0)
        )
        traceability_score = round((verification_coverage + design_coverage) / 2, 4) if trace_summary else 0.0
        if run.gnc_review_result and evidence_sufficiency:
            traceability_score = round(max(traceability_score, evidence_sufficiency), 4)
        consistency_score = 1.0 if not run.review_plus_result.get("cross_document_item_count") else 0.65
        if run.gnc_review_result:
            consistency_score = round(min(consistency_score, conflict_detection), 4)
        smart_committee_warnings: list[str] = []
        if run.review_plus_result.get("review_mode") == "smart_committee":
            committee_limited = bool(run.review_plus_result.get("limited"))
            if committee_limited:
                smart_committee_warnings.append(format_committee_limited_warning())
            citation_coverage = float(run.review_plus_result.get("citation_coverage") or 0.0)
            if citation_coverage < 1.0:
                smart_committee_warnings.append(
                    format_citation_coverage_warning(
                        citation_coverage,
                        run.review_plus_result.get("citation_coverage_source"),
                    )
                )
        business_degradation = sanitize_business_lines(list(run.trace_report.degradation_summary or []))
        business_warnings = sanitize_business_lines(
            [
                *run.structured_bundle.warnings,
                *business_degradation,
                *gnc_failure_warnings,
                *smart_committee_warnings,
            ]
        )
        run.trace_report.degradation_summary = business_degradation
        return score_super_agent_quality(
            run,
            traceability_score=traceability_score,
            consistency_score=consistency_score,
            expert_consensus_score=expert_consensus,
            evidence_sufficiency_score=evidence_sufficiency,
            conflict_detection_score=conflict_detection,
            warnings=business_warnings,
            extra_failure_count=len(committee_failures),
        )