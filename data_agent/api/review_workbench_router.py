"""Unified review workbench BFF — GNC + Review-Plus read aggregation."""

from __future__ import annotations

from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException

from data_agent.api.auth import verify_api_token
from data_agent.api.gnc_review_router import (
    GNCReviewService,
    _requires_arbitration_run,
    get_gnc_review_service,
)
from data_agent.core.contracts import paginated_response, success_response
from data_agent.integrations.satellite_review.gnc_schemas import GNCReviewRun, GNCReviewStatus
from data_agent.review_plus.gatekeeping_adapter import evaluate_review_plus_gatekeeping
from data_agent.review_plus.service import get_review_plus_service
from data_agent.review_workbench.gnc_workbench_service import (
    apply_arbitration,
    build_workbench_detail as build_gnc_detail,
    _gnc_completed_steps,
    paginate_events,
    patch_rid_item,
    project_committee,
    project_cross_document as project_gnc_cross_document,
    project_decision,
    project_evidences,
    project_findings as project_gnc_findings,
    project_flow as project_gnc_flow,
    project_gatekeeping as project_gnc_gatekeeping,
    project_materials as project_gnc_materials,
    project_minutes,
    project_report as project_gnc_report,
    project_rid_items,
    project_traceability as project_gnc_traceability,
)
from data_agent.review_workbench.mappers import map_gnc_status_to_phase, map_review_plus_status_to_phase
from data_agent.review_workbench.review_plus_workbench_service import (
    build_workbench_detail as build_review_plus_detail,
    project_check_items,
    project_coverage,
    project_cross_document as project_rp_cross_document,
    project_decision as project_rp_decision,
    project_events as project_rp_events,
    project_findings as project_rp_findings,
    project_flow as project_rp_flow,
    project_gatekeeping as project_rp_gatekeeping,
    project_materials as project_rp_materials,
    project_report as project_rp_report,
    project_traceability as project_rp_traceability,
)
from data_agent.review_workbench.super_agent_workbench_service import (
    build_workbench_detail as build_super_agent_detail,
    project_check_items as project_super_agent_check_items,
    project_closure as project_super_agent_closure,
    project_committee as project_super_agent_committee,
    project_decision as project_super_agent_decision,
    project_events as project_super_agent_events,
    project_evidences as project_super_agent_evidences,
    project_findings as project_super_agent_findings,
    project_flow as project_super_agent_flow,
    project_materials as project_super_agent_materials,
    project_quality as project_super_agent_quality,
    project_report as project_super_agent_report,
    project_routes as project_super_agent_routes,
)
from data_agent.review_workbench.schemas import GNCArbitrationRequest, GNCRidPatchRequest, ReviewType

router = APIRouter(
    prefix="/api/v1/review-workbench",
    tags=["review-workbench"],
    dependencies=[Depends(verify_api_token)],
)

_READ_RESOURCES = {
    "flow",
    "materials",
    "gatekeeping",
    "findings",
    "rid_items",
    "traceability",
    "cross_document",
    "evidences",
    "committee",
    "decision",
    "minutes",
    "report",
    "events",
    "check_items",
    "coverage",
    "routes",
    "closure",
    "quality",
}


def _parse_review_type(review_type: str) -> ReviewType:
    normalized = (review_type or "").strip().lower()
    if normalized in {ReviewType.GNC.value, "gnc-review"}:
        return ReviewType.GNC
    if normalized in {ReviewType.REVIEW_PLUS.value, "review-plus", "review_plus"}:
        return ReviewType.REVIEW_PLUS
    if normalized in {ReviewType.SUPER_AGENT.value, "super-agent", "super_agent"}:
        return ReviewType.SUPER_AGENT
    raise HTTPException(status_code=422, detail=f"不支持的 review_type: {review_type}")


def _gnc_not_found(review_id: str) -> None:
    raise HTTPException(status_code=404, detail=f"GNC 审查任务不存在: {review_id}")


def _review_plus_not_found(review_id: str) -> None:
    raise HTTPException(status_code=404, detail=f"Review-Plus 任务不存在: {review_id}")


def _super_agent_not_found(review_id: str) -> None:
    raise HTTPException(status_code=404, detail=f"Super Agent Run 不存在: {review_id}")


def _load_gnc(review_id: str) -> GNCReviewRun:
    run = get_gnc_review_service().get_review(review_id)
    if not run:
        _gnc_not_found(review_id)
    return run


def _load_review_plus(review_id: str):
    task = get_review_plus_service().get_review(review_id)
    if not task:
        _review_plus_not_found(review_id)
    return task


def _load_super_agent(review_id: str):
    from data_agent.super_agent.service import get_super_agent_service

    run = get_super_agent_service().get_run(review_id)
    if not run:
        _super_agent_not_found(review_id)
    return run


@router.get(
    "/{review_type}/{review_id}",
    summary="统一审查工作台详情",
)
async def get_workbench_detail(review_type: str, review_id: str):
    kind = _parse_review_type(review_type)
    if kind == ReviewType.GNC:
        return success_response(build_gnc_detail(_load_gnc(review_id)).model_dump(mode="json"))
    if kind == ReviewType.SUPER_AGENT:
        return success_response(build_super_agent_detail(_load_super_agent(review_id)).model_dump(mode="json"))
    return success_response(build_review_plus_detail(_load_review_plus(review_id)).model_dump(mode="json"))


@router.get(
    "/{review_type}/{review_id}/phase",
    summary="工作台阶段",
)
async def get_workbench_phase(review_type: str, review_id: str):
    kind = _parse_review_type(review_type)
    if kind == ReviewType.GNC:
        run = _load_gnc(review_id)
        phase = map_gnc_status_to_phase(
            run.status.value if isinstance(run.status, GNCReviewStatus) else run.status,
            current_step=run.current_step,
            completed_steps=_gnc_completed_steps(run),
        )
    else:
        detail = (
            build_super_agent_detail(_load_super_agent(review_id))
            if kind == ReviewType.SUPER_AGENT
            else build_review_plus_detail(_load_review_plus(review_id))
        )
        phase = detail.workbench_phase
    return success_response({"workbench_phase": phase.value})


@router.get(
    "/{review_type}/{review_id}/visible-tabs",
    summary="可见 Tab 列表",
)
async def get_visible_tabs(review_type: str, review_id: str):
    kind = _parse_review_type(review_type)
    if kind == ReviewType.GNC:
        detail = build_gnc_detail(_load_gnc(review_id))
    elif kind == ReviewType.SUPER_AGENT:
        detail = build_super_agent_detail(_load_super_agent(review_id))
    else:
        detail = build_review_plus_detail(_load_review_plus(review_id))
    return success_response({"visible_tabs": detail.visible_tabs, "workbench_phase": detail.workbench_phase.value})


def _dispatch_read(
    review_type: ReviewType,
    review_id: str,
    resource: str,
) -> Any:
    if resource not in _READ_RESOURCES:
        raise HTTPException(status_code=404, detail=f"未知资源: {resource}")

    if review_type == ReviewType.GNC:
        run = _load_gnc(review_id)
        projections: dict[str, Callable[[], Any]] = {
            "flow": lambda: project_gnc_flow(run),
            "materials": lambda: project_gnc_materials(run),
            "gatekeeping": lambda: project_gnc_gatekeeping(run),
            "findings": lambda: project_gnc_findings(run),
            "rid_items": lambda: project_rid_items(run),
            "traceability": lambda: project_gnc_traceability(run),
            "cross_document": lambda: project_gnc_cross_document(run),
            "evidences": lambda: project_evidences(run),
            "committee": lambda: project_committee(run),
            "decision": lambda: project_decision(run),
            "minutes": lambda: project_minutes(run),
            "report": lambda: project_gnc_report(run),
            "events": lambda: list(run.events),
            "check_items": lambda: [],
            "coverage": lambda: {},
        }
        return projections[resource]()

    if review_type == ReviewType.SUPER_AGENT:
        run = _load_super_agent(review_id)
        projections = {
            "flow": lambda: project_super_agent_flow(run),
            "materials": lambda: project_super_agent_materials(run),
            "gatekeeping": lambda: {},
            "findings": lambda: project_super_agent_findings(run),
            "rid_items": lambda: [],
            "traceability": lambda: {},
            "cross_document": lambda: [],
            "evidences": lambda: project_super_agent_evidences(run),
            "committee": lambda: project_super_agent_committee(run),
            "decision": lambda: project_super_agent_decision(run),
            "minutes": lambda: {},
            "report": lambda: project_super_agent_report(run),
            "events": lambda: project_super_agent_events(run),
            "check_items": lambda: project_super_agent_check_items(run),
            "coverage": lambda: {},
            "routes": lambda: project_super_agent_routes(run),
            "closure": lambda: project_super_agent_closure(run),
            "quality": lambda: project_super_agent_quality(run),
        }
        return projections[resource]()

    task = _load_review_plus(review_id)
    if resource == "gatekeeping" and not task.gatekeeping_result:
        task.gatekeeping_result = evaluate_review_plus_gatekeeping(task).model_dump()
        get_review_plus_service()._save_task(task)
    projections = {
        "flow": lambda: project_rp_flow(task),
        "materials": lambda: project_rp_materials(task),
        "gatekeeping": lambda: project_rp_gatekeeping(task),
        "findings": lambda: project_rp_findings(task),
        "rid_items": lambda: [],
        "traceability": lambda: project_rp_traceability(task),
        "cross_document": lambda: project_rp_cross_document(task),
        "evidences": lambda: (task.evidence_pool or {}).get("items") or (task.evidence_pool or {}).get("evidences") or [],
        "committee": lambda: {
            "specialist_reviews": task.specialist_reviews or [],
            "chief_review_plan": task.chief_review_plan or {},
        },
        "decision": lambda: project_rp_decision(task),
        "minutes": lambda: {},
        "report": lambda: project_rp_report(task),
        "events": lambda: project_rp_events(task),
        "check_items": lambda: project_check_items(task),
        "coverage": lambda: project_coverage(task),
    }
    return projections[resource]()


@router.get(
    "/{review_type}/{review_id}/events-page",
    summary="分页审查事件",
)
async def get_events_page(review_type: str, review_id: str, page: int = 1, size: int = 50):
    kind = _parse_review_type(review_type)
    if kind == ReviewType.GNC:
        run = _load_gnc(review_id)
        items, total = paginate_events(list(run.events), page=page, size=size)
    else:
        task = _load_review_plus(review_id)
        items, total = paginate_events(list(task.events or []), page=page, size=size)
    return paginated_response(items, page=page, size=size, total=total)


@router.get(
    "/{review_type}/{review_id}/{resource}",
    summary="统一工作台读聚合子资源",
)
async def get_workbench_resource(review_type: str, review_id: str, resource: str):
    kind = _parse_review_type(review_type)
    if resource in {"phase", "visible-tabs", "visible_tabs"}:
        raise HTTPException(status_code=404, detail="请使用专用 phase / visible-tabs 端点")
    data = _dispatch_read(kind, review_id, resource.replace("-", "_"))
    return success_response(data)


@router.post(
    "/{review_type}/{review_id}/arbitration",
    summary="提交 GNC 人工仲裁（仅 gnc）",
)
async def submit_arbitration(review_type: str, review_id: str, payload: GNCArbitrationRequest):
    if _parse_review_type(review_type) != ReviewType.GNC:
        raise HTTPException(status_code=405, detail="仅 GNC 审查支持人工仲裁")
    svc: GNCReviewService = get_gnc_review_service()
    run = _load_gnc(review_id)
    if not _requires_arbitration_run(run):
        raise HTTPException(status_code=409, detail="当前审查无需人工仲裁")
    updated = apply_arbitration(run, payload)
    svc.save_run(run)
    svc.record_event(
        review_id,
        "arbitration_submitted",
        {"status": payload.status, "decision_count": len(payload.decisions)},
    )
    return success_response(
        {
            "review_id": review_id,
            "status": run.status.value if isinstance(run.status, GNCReviewStatus) else run.status,
            "arbitration": updated,
        }
    )


@router.patch(
    "/{review_type}/{review_id}/rid/{rid_id}",
    summary="更新 GNC RID（仅 gnc）",
)
async def patch_rid(review_type: str, review_id: str, rid_id: str, payload: GNCRidPatchRequest):
    if _parse_review_type(review_type) != ReviewType.GNC:
        raise HTTPException(status_code=405, detail="仅 GNC 审查支持 RID 台账")
    svc = get_gnc_review_service()
    run = _load_gnc(review_id)
    if not project_rid_items(run):
        raise HTTPException(status_code=409, detail="当前审查尚无 RID 数据")
    updated = patch_rid_item(run, rid_id, payload)
    if updated is None:
        raise HTTPException(status_code=404, detail=f"RID 不存在: {rid_id}")
    svc.save_run(run)
    svc.record_event(review_id, "rid_updated", {"rid_id": rid_id, "status": updated.get("status")})
    return success_response(updated)
