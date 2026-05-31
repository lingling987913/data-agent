"""Bridge Review-Plus workflow results to Data Agent task API."""

from __future__ import annotations

from typing import Any, Callable

from data_agent.domain.material_roles import ReviewCheckItem
from data_agent.review_plus.schemas import CreateReviewPlusRequest, ReviewPlusTask
from data_agent.review_plus.service import get_review_plus_service
from data_agent.workflows.review_plus_workflow import run_review_plus_workflow


def run_review_plus_package(
    *,
    name: str,
    uploads: list[tuple[str, bytes]],
    parser_type: str = "local",
    on_step: Callable[[str, float], None] | None = None,
) -> ReviewPlusTask:
    svc = get_review_plus_service()
    task = svc.create_review(CreateReviewPlusRequest(name=name))
    svc.upload_materials(task.review_plus_id, uploads, parser_type=parser_type)
    if on_step:
        on_step("review_plus_workflow", 0.6)
    result = run_review_plus_workflow(task.review_plus_id)
    if result.get("failed_step"):
        raise RuntimeError(
            f"Review-Plus workflow failed at {result['failed_step']}: {result.get('error')}"
        )
    final = svc.get_review(task.review_plus_id)
    if not final:
        raise RuntimeError("Review-Plus task missing after workflow")
    if on_step:
        on_step("review_plus_workflow", 0.95)
    return final


def map_review_plus_to_task_fields(rp_task: ReviewPlusTask) -> dict[str, Any]:
    check_items = [
        ReviewCheckItem(
            item_no=item.item_no,
            check_subject=item.title,
            check_target=item.applicable_scope,
            requirement=item.requirement_text,
            remark=(item.source_quote or "")[:200],
        )
        for item in rp_task.check_items
    ]
    findings = [f.model_dump(mode="json") for f in rp_task.findings]
    cross_doc_findings = list(rp_task.cross_document_review_items or [])
    review_markdown = rp_task.report_markdown or (rp_task.report.markdown if rp_task.report else "")
    review_conclusion = rp_task.report.conclusion if rp_task.report else ""
    return {
        "check_items": check_items,
        "findings": findings,
        "cross_doc_findings": cross_doc_findings,
        "review_report_markdown": review_markdown,
        "review_conclusion": review_conclusion,
        "coverage_matrix": rp_task.coverage_matrix,
        "traceability_result": rp_task.traceability_result,
        "agent_run_traces": rp_task.agent_run_traces,
    }
