"""Review-Plus REST API — 对齐 aq-aero review_plus_router。"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Body, Depends, File, Form, HTTPException, Query, Response, UploadFile

from data_agent.api.auth import verify_api_token
from data_agent.core.contracts import paginated_response, success_response
from data_agent.review_plus.gatekeeping_adapter import evaluate_review_plus_gatekeeping
from data_agent.review_plus.schemas import (
    CreateReviewPlusRequest,
    ReviewPlusMaterialRole,
    ReviewPlusParserType,
    ReviewPlusStatus,
)
from data_agent.review_plus.service import get_review_plus_service
from data_agent.workflows.review_plus_workflow import (
    confirm_review_plus_trace_link,
    execute_cross_document_review,
    execute_traceability,
    reject_review_plus_trace_link,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/review-plus/reviews",
    dependencies=[Depends(verify_api_token)],
)


def _not_found(review_id: str) -> None:
    raise HTTPException(status_code=404, detail=f"Review-Plus 任务不存在: {review_id}")


@router.post(
    "",
    tags=["review-plus-lifecycle"],
    summary="创建审查任务",
)
async def create_review(req: CreateReviewPlusRequest):
    if not req.name.strip():
        raise HTTPException(status_code=422, detail="审查任务名称不能为空")
    task = get_review_plus_service().create_review(req)
    return success_response(task.model_dump())


@router.get(
    "",
    tags=["review-plus-lifecycle"],
    summary="分页列出审查任务",
)
async def list_reviews(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    status: Optional[ReviewPlusStatus] = Query(None),
):
    svc = get_review_plus_service()
    tasks = svc.list_reviews()
    if status:
        tasks = [task for task in tasks if task.status == status.value]
    total = len(tasks)
    start = (page - 1) * size
    page_tasks = tasks[start : start + size]
    return paginated_response(
        [task.model_dump() for task in page_tasks],
        page=page,
        size=size,
        total=total,
    )


@router.get(
    "/{review_id}",
    tags=["review-plus-lifecycle"],
    summary="获取审查任务详情",
)
async def get_review(review_id: str):
    task = get_review_plus_service().get_review(review_id)
    if not task:
        _not_found(review_id)
    return success_response(task.model_dump())


@router.delete(
    "/{review_id}",
    tags=["review-plus-lifecycle"],
    summary="删除审查任务",
    description="运行中任务需 `force=true` 方可删除。",
)
async def delete_review(
    review_id: str,
    force: bool = Query(False),
):
    svc = get_review_plus_service()
    try:
        result = svc.delete_review(review_id, force=force)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not result.get("deleted"):
        _not_found(review_id)
    return success_response(result)


@router.get(
    "/{review_id}/gatekeeping",
    tags=["review-plus-gatekeeping"],
    summary="获取送审包门禁结果",
)
async def get_gatekeeping(review_id: str):
    svc = get_review_plus_service()
    task = svc.get_review(review_id)
    if not task:
        _not_found(review_id)
    if not task.gatekeeping_result:
        gate_result = evaluate_review_plus_gatekeeping(task)
        task.gatekeeping_result = gate_result.model_dump()
        svc._save_task(task)
    return success_response(task.gatekeeping_result)


@router.post(
    "/{review_id}/gatekeeping/recheck",
    tags=["review-plus-gatekeeping"],
    summary="重新计算送审包门禁",
)
async def recheck_gatekeeping(review_id: str):
    task = get_review_plus_service().recheck_gatekeeping(review_id)
    if not task:
        _not_found(review_id)
    return success_response(task.gatekeeping_result)


@router.post(
    "/{review_id}/upload",
    tags=["review-plus-materials"],
    summary="上传送审材料",
    description="multipart 上传；`parser_type` 可选 auto / mineru / local 等。",
)
async def upload_materials(
    review_id: str,
    files: list[UploadFile] = File(...),
    parser_type: ReviewPlusParserType = Form(ReviewPlusParserType.AUTO),
):
    svc = get_review_plus_service()
    if not svc.get_review(review_id):
        _not_found(review_id)

    uploads: list[tuple[str, bytes]] = []
    for file in files:
        uploads.append((file.filename or "", await file.read()))

    try:
        task = svc.upload_materials(review_id, uploads, parser_type=parser_type.value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not task:
        _not_found(review_id)
    return success_response(
        {
            "review_plus_id": task.review_plus_id,
            "status": task.status,
            "materials": [material.model_dump() for material in task.materials],
            "gatekeeping_result": task.gatekeeping_result,
        }
    )


@router.post(
    "/{review_id}/parse",
    tags=["review-plus-materials"],
    summary="执行 Step 3 材料解析",
    description="上传与分类完成后、审查执行前调用；结果写入 task.parse_artifact。`force_reparse=true` 可强制重解析。",
)
async def parse_materials(
    review_id: str,
    body: dict = Body(default_factory=dict),
):
    svc = get_review_plus_service()
    if not svc.get_review(review_id):
        _not_found(review_id)
    force_reparse = bool(body.get("force_reparse"))
    try:
        task = svc.parse_materials(review_id, force_reparse=force_reparse)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not task:
        _not_found(review_id)
    return success_response(
        {
            "review_plus_id": task.review_plus_id,
            "status": task.status,
            "parse_artifact": task.parse_artifact,
            "batch_summary": (task.parse_artifact or {}).get("batch_summary") or {},
            "materials": [material.model_dump() for material in task.materials],
        }
    )


@router.post(
    "/{review_id}/materials/{material_name}/reparse",
    tags=["review-plus-materials"],
    summary="指定解析器重解析材料",
)
async def reparse_material(
    review_id: str,
    material_name: str,
    body: dict = Body(default_factory=dict),
):
    svc = get_review_plus_service()
    if not svc.get_review(review_id):
        _not_found(review_id)
    parser_type = str(body.get("parser_type") or ReviewPlusParserType.AUTO.value)
    try:
        task = svc.reparse_material(review_id, material_name, parser_type=parser_type)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not task:
        _not_found(review_id)
    material = next((item for item in task.materials if item.name == material_name), None)
    return success_response(
        {
            "status": task.status,
            "material": material.model_dump() if material else None,
            "gatekeeping_result": task.gatekeeping_result,
        }
    )


@router.post(
    "/{review_id}/classify",
    tags=["review-plus-materials"],
    summary="自动分类材料角色",
)
async def classify_materials(review_id: str):
    svc = get_review_plus_service()
    if not svc.get_review(review_id):
        _not_found(review_id)
    task = svc.classify_materials(review_id)
    if not task:
        _not_found(review_id)
    svc._auto_confirm_classified_roles(review_id)
    task = svc.recheck_gatekeeping(review_id) or task
    return success_response(task.model_dump())


@router.get(
    "/{review_id}/classification",
    tags=["review-plus-materials"],
    summary="获取材料分类结果",
)
async def get_classification(review_id: str):
    result = get_review_plus_service().get_classification(review_id)
    if result is None:
        _not_found(review_id)
    return success_response(result)


@router.post(
    "/{review_id}/materials/{material_name}/role",
    tags=["review-plus-materials"],
    summary="人工修正材料角色",
)
async def update_material_role(review_id: str, material_name: str, body: dict):
    svc = get_review_plus_service()
    task = svc.get_review(review_id)
    if not task:
        _not_found(review_id)

    material = next((item for item in task.materials if item.name == material_name), None)
    if not material:
        raise HTTPException(status_code=404, detail=f"Material '{material_name}' not found")

    material_fields = type(material).model_fields
    if "role" in body:
        role_value = body["role"]
        try:
            material.role = ReviewPlusMaterialRole(role_value)
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid role '{role_value}'. Valid roles: {[role.value for role in ReviewPlusMaterialRole]}",
            ) from exc
    if "document_version" in body and "document_version" in material_fields:
        material.document_version = body["document_version"]
    if "baseline_id" in body and "baseline_id" in material_fields:
        material.baseline_id = body["baseline_id"]
    if "role_confirmed" in material_fields:
        material.role_confirmed = True

    svc._save_task(task)
    svc.invalidate_derived_results(review_id)
    svc.record_event(
        review_id,
        "material_role_confirmed",
        {
            "material_name": material.name,
            "role": material.role.value if hasattr(material.role, "value") else material.role,
        },
    )
    return success_response({"status": "updated", "material": material.model_dump()})


@router.get(
    "/{review_id}/check-items",
    tags=["review-plus-results"],
    summary="获取检查项列表",
)
async def get_check_items(review_id: str):
    result = get_review_plus_service().get_check_items(review_id)
    if result is None:
        _not_found(review_id)
    return success_response(result)


@router.post(
    "/{review_id}/start",
    tags=["review-plus-execution"],
    summary="启动十步审查 workflow",
    description="后台异步执行；可通过详情接口轮询 `status`。",
)
async def start_review(review_id: str, background_tasks: BackgroundTasks):
    svc = get_review_plus_service()
    try:
        task = svc.start_review(review_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not task:
        _not_found(review_id)
    background_tasks.add_task(svc.continue_started_review, review_id)
    return success_response(task.model_dump())


@router.post(
    "/{review_id}/continue",
    tags=["review-plus-execution"],
    summary="继续/补偿执行审查",
)
async def continue_review(review_id: str, background_tasks: BackgroundTasks):
    svc = get_review_plus_service()
    task = svc.get_review(review_id)
    if not task:
        _not_found(review_id)
    if task.status == ReviewPlusStatus.COMPLETED.value:
        raise HTTPException(status_code=400, detail="审查已完成，无需继续执行")
    if not task.materials:
        raise HTTPException(status_code=400, detail="请先上传送审材料")
    task = svc.recheck_gatekeeping(review_id) or task
    gatekeeping = task.gatekeeping_result or {}
    if gatekeeping.get("gate_status") == "blocked" or gatekeeping.get("can_start_review") is False:
        raise HTTPException(
            status_code=400,
            detail=gatekeeping.get("gate_summary") or "送审包门禁未通过，请先修复材料",
        )
    svc.record_event(review_id, "review_continue_requested", {"status": task.status})
    background_tasks.add_task(svc.continue_started_review, review_id)
    return success_response(task.model_dump())


@router.post(
    "/{review_id}/restart",
    tags=["review-plus-execution"],
    summary="清空派生结果并重启审查",
)
async def restart_review(review_id: str, background_tasks: BackgroundTasks):
    svc = get_review_plus_service()
    task = svc.get_review(review_id)
    if not task:
        _not_found(review_id)
    if not task.materials:
        raise HTTPException(status_code=400, detail="请先上传送审材料")
    try:
        task = svc.restart_review_from_source(review_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not task:
        _not_found(review_id)
    background_tasks.add_task(svc.continue_started_review, review_id)
    return success_response(task.model_dump())


@router.get(
    "/{review_id}/events",
    tags=["review-plus-results"],
    summary="获取审查事件流",
)
async def get_events(review_id: str):
    events = get_review_plus_service().get_events(review_id)
    if events is None:
        _not_found(review_id)
    return success_response(events)


@router.get(
    "/{review_id}/agent-traces",
    tags=["review-plus-results"],
    summary="获取 Agent 运行轨迹",
)
async def get_agent_traces(review_id: str):
    task = get_review_plus_service().get_review(review_id)
    if not task:
        _not_found(review_id)
    return success_response(task.agent_run_traces or [])


@router.get(
    "/{review_id}/findings",
    tags=["review-plus-results"],
    summary="获取逐项审查结论",
)
async def get_findings(review_id: str):
    task = get_review_plus_service().get_review(review_id)
    if not task:
        _not_found(review_id)
    return success_response([f.model_dump() for f in task.findings])


@router.get(
    "/{review_id}/mappings",
    tags=["review-plus-results"],
    summary="获取检查项章节映射",
)
async def get_mappings(review_id: str):
    task = get_review_plus_service().get_review(review_id)
    if not task:
        _not_found(review_id)
    return success_response([m.model_dump() for m in task.section_mappings])


@router.get(
    "/{review_id}/coverage-matrix",
    tags=["review-plus-results"],
    summary="获取 Harness 覆盖矩阵",
)
async def get_coverage_matrix(review_id: str):
    task = get_review_plus_service().get_review(review_id)
    if not task:
        _not_found(review_id)
    return success_response(task.coverage_matrix or {})


@router.get(
    "/{review_id}/traceability",
    tags=["review-plus-traceability"],
    summary="获取需求追溯矩阵",
    description="若尚未生成则按需执行追溯步骤。",
)
async def get_traceability(review_id: str):
    svc = get_review_plus_service()
    task = svc.get_review(review_id)
    if not task:
        _not_found(review_id)
    if not task.traceability_result:
        execute_traceability(review_id)
        task = svc.get_review(review_id)
    return success_response(task.traceability_result if task else None)


@router.get(
    "/{review_id}/cross-document-review-items",
    tags=["review-plus-traceability"],
    summary="获取跨文档一致性审查项",
)
async def get_cross_document_review_items(review_id: str):
    svc = get_review_plus_service()
    task = svc.get_review(review_id)
    if not task:
        _not_found(review_id)
    if not task.cross_document_review_items:
        execute_cross_document_review(review_id)
        task = svc.get_review(review_id)
    return success_response(task.cross_document_review_items if task else [])


@router.post(
    "/{review_id}/traceability/links/{link_id}/confirm",
    tags=["review-plus-traceability"],
    summary="人工确认追溯链路",
)
async def confirm_trace_link(
    review_id: str,
    link_id: str,
    body: dict = Body(default_factory=dict),
):
    svc = get_review_plus_service()
    task = svc.get_review(review_id)
    if not task:
        _not_found(review_id)
    try:
        confirm_review_plus_trace_link(
            task,
            link_id,
            user=str(body.get("confirmed_by") or body.get("user") or "human"),
            rationale=str(body.get("rationale") or ""),
        )
        svc._save_task(task)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return success_response(task.traceability_result)


@router.post(
    "/{review_id}/traceability/links/{link_id}/reject",
    tags=["review-plus-traceability"],
    summary="人工拒绝追溯链路",
)
async def reject_trace_link(
    review_id: str,
    link_id: str,
    body: dict = Body(default_factory=dict),
):
    svc = get_review_plus_service()
    task = svc.get_review(review_id)
    if not task:
        _not_found(review_id)
    rejection_reason = str(body.get("rationale") or body.get("reason") or "").strip()
    if not rejection_reason:
        raise HTTPException(status_code=400, detail="拒绝链路必须填写原因")
    try:
        reject_review_plus_trace_link(
            task,
            link_id,
            user=str(body.get("rejected_by") or body.get("user") or "human"),
            rationale=rejection_reason,
        )
        svc._save_task(task)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return success_response(task.traceability_result)


@router.get(
    "/{review_id}/report",
    tags=["review-plus-results"],
    summary="获取结构化审查报告 JSON",
)
async def get_report(review_id: str):
    task = get_review_plus_service().get_review(review_id)
    if not task:
        _not_found(review_id)
    if not task.report:
        return success_response(None)
    return success_response(task.report.model_dump())


@router.get(
    "/{review_id}/report.md",
    tags=["review-plus-results"],
    summary="下载 Markdown 审查报告",
    response_class=Response,
)
async def get_report_markdown(review_id: str):
    task = get_review_plus_service().get_review(review_id)
    if not task:
        _not_found(review_id)
    from data_agent.review_plus.report_service import build_review_plus_markdown

    markdown = build_review_plus_markdown(task)
    if not markdown:
        return Response("未生成审查报告。\n", media_type="text/markdown; charset=utf-8")
    return Response(markdown, media_type="text/markdown; charset=utf-8")
