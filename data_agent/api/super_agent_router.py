"""Review Data Super Agent REST API."""

from __future__ import annotations

import asyncio
import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from data_agent.api.auth import verify_api_token
from data_agent.core.config import SUPER_AGENT_UPLOAD_DIR
from data_agent.core.agent_debug_log import agent_debug_log
from data_agent.core.contracts import error_response, paginated_response, success_response
from data_agent.super_agent.schemas import (
    CreateSuperAgentRunRequest,
    SuperAgentParseRunRequest,
    SuperAgentReviewMode,
    SuperAgentReviewRunRequest,
    SuperAgentStatus,
    SaveWizardCheckpointRequest,
)
from data_agent.super_agent.service import enrich_material_previews, get_super_agent_service

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/super-agent",
    tags=["super-agent"],
    dependencies=[Depends(verify_api_token)],
)


def _file_content_preview(raw: bytes, *, max_chars: int = 500) -> str:
    return raw.decode("utf-8", errors="ignore")[:max_chars]


def _safe_upload_filename(name: str) -> str:
    import re

    cleaned = re.sub(r"[^A-Za-z0-9._\-\u4e00-\u9fff]+", "_", (name or "").strip())
    cleaned = cleaned.strip("._")
    return cleaned or "material.bin"


def _parse_preview_job_payload(
    run_id: str,
    job_id: str,
    *,
    status: str,
    progress: int,
    message: str,
    error: str = "",
) -> dict:
    return {
        "job_id": job_id,
        "run_id": run_id,
        "status": status,
        "progress": max(0, min(100, progress)),
        "message": message,
        "error": error,
        "updated_at": "",
    }


def _set_parse_preview_job(
    run_id: str,
    job_id: str,
    *,
    status: str,
    progress: int,
    message: str,
    error: str = "",
) -> dict:
    from data_agent.super_agent import helpers

    svc = get_super_agent_service()
    run = svc.get_run(run_id)
    if not run:
        raise ValueError(f"Super Agent run not found: {run_id}")
    job = _parse_preview_job_payload(
        run_id,
        job_id,
        status=status,
        progress=progress,
        message=message,
        error=error,
    )
    job["updated_at"] = helpers._now()
    run.phase_artifacts["parse_preview_job"] = job
    svc.checkpoint_run(run)
    return job


def _parse_preview_job_is_active(job: dict) -> bool:
    return str(job.get("status") or "") in {"queued", "running"}


def _parse_preview_job_recently_updated(updated_at: str, *, max_age_seconds: int = 1800) -> bool:
    from data_agent.super_agent import helpers

    parsed = helpers._parse_iso_timestamp(updated_at)
    if parsed is None:
        return False
    from datetime import datetime

    age = (datetime.now() - parsed).total_seconds()
    return age >= 0 and age <= max_age_seconds


def _execute_parse_preview_background(run_id: str, job_id: str, force_reparse: bool) -> None:
    from data_agent.core.config import SUPER_AGENT_RUNS_DIR
    from data_agent.parsing.parse_figure_context import bind_figure_storage, reset_figure_storage
    from data_agent.parsing.parse_preview_progress import (
        bind_progress_callback,
        reset_progress_callback,
    )

    def _on_progress(progress: int, message: str) -> None:
        try:
            svc = get_super_agent_service()
            run = svc.get_run(run_id)
            if not run:
                return
            job = dict(run.phase_artifacts.get("parse_preview_job") or {})
            if job.get("job_id") != job_id:
                return
            if not _parse_preview_job_is_active(job):
                return
            _set_parse_preview_job(
                run_id,
                job_id,
                status="running",
                progress=progress,
                message=message,
            )
        except Exception:
            logger.debug("[SuperAgent] parse preview progress update skipped", exc_info=True)

    token = bind_progress_callback(_on_progress)
    figure_token = bind_figure_storage(run_id, SUPER_AGENT_RUNS_DIR / run_id / "figures")
    try:
        _set_parse_preview_job(
            run_id,
            job_id,
            status="running",
            progress=10,
            message="正在解析材料…",
        )
        svc = get_super_agent_service()
        preview = svc.preview_parse_from_run(run_id, force_reparse=force_reparse)
        run = svc.get_run(run_id)
        if not run:
            raise ValueError(f"Super Agent run not found: {run_id}")
        job = _parse_preview_job_payload(
            run_id,
            job_id,
            status="completed",
            progress=100,
            message="解析预览完成",
        )
        from data_agent.super_agent import helpers

        job["updated_at"] = helpers._now()
        run.phase_artifacts["parse_preview_job"] = job
        run.parse_preview = preview
        svc.checkpoint_run(run)
    except Exception as exc:
        logger.exception("[SuperAgent] parse preview background failed run_id=%s job_id=%s", run_id, job_id)
        try:
            _set_parse_preview_job(
                run_id,
                job_id,
                status="failed",
                progress=100,
                message="解析预览失败",
                error=str(exc),
            )
        except Exception:
            logger.exception("[SuperAgent] failed to persist parse preview job error")
    finally:
        reset_figure_storage(figure_token)
        reset_progress_callback(token)


def _is_temporary_office_file(name: str) -> bool:
    return Path(name or "").name.startswith("~$")


def _relative_super_agent_path(path: Path) -> str:
    root = SUPER_AGENT_UPLOAD_DIR.resolve()
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(root))
    except ValueError as exc:
        raise HTTPException(status_code=500, detail="上传文件路径超出 Super Agent 上传目录") from exc


def _execute_super_agent_run_sync(
    run_id: str,
    req: CreateSuperAgentRunRequest,
    *,
    resume: bool = False,
) -> None:
    svc = get_super_agent_service()
    svc.execute_run(run_id, request=req, resume=resume)
    run = svc.get_run(run_id)
    agent_debug_log(
        "super_agent_router.py:_execute_super_agent_run_background",
        "background execute finished",
        {
            "run_id": run_id,
            "status": str(run.status if run else "missing"),
            "error": (run.error if run else "")[:200],
        },
        hypothesis_id="D",
        run_id="post-fix",
    )


async def _execute_super_agent_review_background(
    run_id: str,
    req: SuperAgentReviewRunRequest | None = None,
) -> None:
    await asyncio.to_thread(_execute_super_agent_review_sync, run_id, req)


def _execute_super_agent_review_sync(
    run_id: str,
    req: SuperAgentReviewRunRequest | None = None,
) -> None:
    svc = get_super_agent_service()
    svc.execute_review_run(run_id, req=req)
    run = svc.get_run(run_id)
    agent_debug_log(
        "super_agent_router.py:_execute_super_agent_review_background",
        "background review finished",
        {
            "run_id": run_id,
            "status": str(run.status if run else "missing"),
            "error": (run.error if run else "")[:200],
        },
        hypothesis_id="D",
        run_id="post-fix",
    )


async def _execute_super_agent_run_background(
    run_id: str,
    req: CreateSuperAgentRunRequest,
    *,
    resume: bool = False,
) -> None:
    await asyncio.to_thread(_execute_super_agent_run_sync, run_id, req, resume=resume)


def _run_response(run):
    data = run.model_dump(mode="json")
    if run.status == SuperAgentStatus.FAILED:
        return JSONResponse(
            status_code=422,
            content=error_response(
                message=run.error or "Super Agent run 执行失败",
                code=422,
                data=data,
                status=run.status.value,
                error=run.error,
            ),
        )
    return success_response(data)


@router.get(
    "/capabilities",
    summary="Super Agent 能力清单",
)
def capabilities():
    return success_response(get_super_agent_service().capabilities().model_dump())


@router.post(
    "/benchmarks/builtin",
    summary="运行内置 smoke benchmark",
)
def run_builtin_benchmark():
    try:
        report = get_super_agent_service().run_builtin_benchmark()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return success_response(report)


@router.post(
    "/runs",
    summary="创建 Super Agent Run",
    description="默认 `execute=true` 会立即执行编排：路由 → 结构化 → Review-Plus 委托 → 质量评分。",
)
def create_run(req: CreateSuperAgentRunRequest, background_tasks: BackgroundTasks):
    agent_debug_log(
        "super_agent_router.py:create_run",
        "create_run entry",
        {
            "execute": req.execute,
            "material_count": len(req.materials),
            "requested_route": str(req.requested_route),
        },
        hypothesis_id="D",
        run_id="post-fix",
    )
    if req.materials:
        req = req.model_copy(update={"materials": enrich_material_previews(req.materials)})
    svc = get_super_agent_service()
    should_execute = req.execute
    try:
        run = svc.create_run(req.model_copy(update={"execute": False}))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        agent_debug_log(
            "super_agent_router.py:create_run",
            "create_run uncaught exception",
            {"error_type": type(exc).__name__, "error": str(exc)[:500]},
            hypothesis_id="D",
        )
        raise
    if should_execute:
        run = svc.mark_run_running(run.run_id)
        background_tasks.add_task(_execute_super_agent_run_background, run.run_id, req)
    agent_debug_log(
        "super_agent_router.py:create_run",
        "create_run success",
        {
            "run_id": run.run_id,
            "status": str(run.status),
            "deferred_execute": should_execute,
        },
        hypothesis_id="D",
        run_id="post-fix",
    )
    return success_response(run.model_dump(mode="json"))


@router.post(
    "/uploads",
    summary="批量上传 Super Agent 材料并返回服务端文件引用",
    description="用于 Web 大文件/文件夹上传。Run 只保存 file_path 引用，不保存 content_base64。",
)
async def upload_materials(files: list[UploadFile] = File(...)):
    from data_agent.parsing.orientation import normalized_display_path_for, write_orientation_display_copy
    from data_agent.parsing.material_preview import extract_material_preview

    if not files:
        raise HTTPException(status_code=400, detail="请至少上传一个文件")

    upload_id = f"upl_{uuid.uuid4().hex[:12]}"
    upload_dir = SUPER_AGENT_UPLOAD_DIR / "sessions" / upload_id
    upload_dir.mkdir(parents=True, exist_ok=True)
    materials: list[dict[str, object]] = []
    skipped: list[dict[str, str]] = []

    for index, file in enumerate(files, start=1):
        original_name = (file.filename or f"material-{index}").strip() or f"material-{index}"
        if _is_temporary_office_file(original_name):
            skipped.append({"file_name": original_name, "reason": "temporary_office_file"})
            continue
        raw = await file.read()
        safe_name = _safe_upload_filename(Path(original_name).name)
        file_id = f"file_{index:03d}_{uuid.uuid4().hex[:8]}"
        target = upload_dir / f"{index:03d}-{safe_name}"
        target.write_bytes(raw or b"")
        source_display_path = ""
        normalized_target = normalized_display_path_for(target)
        normalized_changed, _orientation_warnings = write_orientation_display_copy(
            str(target),
            original_name,
            str(normalized_target),
        )
        if normalized_changed:
            source_display_path = _relative_super_agent_path(normalized_target)
        preview = extract_material_preview(str(target), original_name)
        materials.append(
            {
                "name": original_name,
                "file_type": file.content_type or "",
                "content": "",
                "content_base64": "",
                "content_preview": preview,
                "file_path": _relative_super_agent_path(target),
                "source_display_path": source_display_path,
                "upload_id": upload_id,
                "file_id": file_id,
                "file_size": len(raw or b""),
                "parser_type": "auto",
            }
        )

    if not materials:
        raise HTTPException(status_code=400, detail="没有可上传的有效材料")

    return success_response({"upload_id": upload_id, "materials": materials, "skipped": skipped})


@router.post(
    "/runs/{run_id}/resume",
    summary="续跑 Super Agent Run",
    description="用于服务重启后恢复 interrupted/failed/draft（已有材料）状态的 run。",
)
def resume_run(run_id: str, background_tasks: BackgroundTasks):
    svc = get_super_agent_service()
    try:
        run = svc.resume_run(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    req = svc.build_execution_request(run)
    background_tasks.add_task(_execute_super_agent_run_background, run_id, req, resume=True)
    return success_response(run.model_dump(mode="json"))


@router.post(
    "/runs/{run_id}/interrupt",
    summary="手动中断 Super Agent Run",
    description="将 running 状态的 run 标记为 interrupted，后续可通过 resume 续跑。",
)
def interrupt_run(run_id: str):
    svc = get_super_agent_service()
    try:
        run = svc.interrupt_run(run_id)
    except ValueError as exc:
        message = str(exc)
        if "not found" in message.lower():
            raise HTTPException(status_code=404, detail=message) from exc
        if "not running" in message.lower():
            raise HTTPException(status_code=409, detail=message) from exc
        raise HTTPException(status_code=400, detail=message) from exc
    return success_response(run.model_dump(mode="json"))


@router.put(
    "/runs/{run_id}",
    summary="更新 Super Agent Run",
    description="用于先创建 draft run，再补充材料/目标并沿用同一 run_id 启动后台执行。",
)
def update_run(run_id: str, req: CreateSuperAgentRunRequest, background_tasks: BackgroundTasks):
    if req.materials:
        req = req.model_copy(update={"materials": enrich_material_previews(req.materials)})
    svc = get_super_agent_service()
    should_execute = req.execute
    try:
        run = svc.update_run(run_id, req.model_copy(update={"execute": False}))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if should_execute:
        run = svc.mark_run_running(run.run_id)
        background_tasks.add_task(_execute_super_agent_run_background, run.run_id, req)
    return success_response(run.model_dump(mode="json"))


@router.patch(
    "/runs/{run_id}/wizard",
    summary="保存 Super Agent 向导检查点",
    description="仅 draft 状态可写；用于步骤 1–4 的材料/识别/解析预览持久化，便于刷新后恢复。",
)
def save_wizard_checkpoint(run_id: str, req: SaveWizardCheckpointRequest):
    if req.materials:
        req = req.model_copy(update={"materials": enrich_material_previews(req.materials)})
    svc = get_super_agent_service()
    try:
        run = svc.save_wizard_checkpoint(run_id, req)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return success_response(run.model_dump(mode="json"))


@router.post(
    "/runs/{run_id}/classify",
    summary="对已保存材料的 Run 执行 L0/L1 智能识别（步骤 2）",
)
def classify_run_materials(run_id: str):
    svc = get_super_agent_service()
    try:
        classification = svc.classify_run_materials(run_id)
        run = svc.get_run(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("[SuperAgent] classify_run_materials failed run_id=%s", run_id)
        raise HTTPException(status_code=500, detail=f"材料识别失败: {exc}") from exc
    return success_response({"classification": classification, "run": run.model_dump(mode="json") if run else {}})


@router.post(
    "/runs/{run_id}/parse-preview",
    summary="基于步骤 2 识别结果生成分级解析预览（步骤 3）",
)
def parse_preview_from_run(run_id: str, force_reparse: bool = Query(False)):
    svc = get_super_agent_service()
    try:
        preview = svc.preview_parse_from_run(run_id, force_reparse=force_reparse)
        run = svc.get_run(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("[SuperAgent] parse_preview_from_run failed run_id=%s", run_id)
        raise HTTPException(status_code=500, detail=f"材料解析预览失败: {exc}") from exc
    run_payload = run.model_dump(mode="json") if run else {}
    # preview 已单独返回，避免响应体重复携带完整 parse_preview（易超 1MB 导致前端代理 500）
    run_payload.pop("parse_preview", None)
    return success_response({"preview": preview, "run": run_payload})


@router.post(
    "/runs/{run_id}/parse-preview/jobs",
    summary="启动后台解析预览任务（步骤 3）",
)
def start_parse_preview_job(
    run_id: str,
    background_tasks: BackgroundTasks,
    force_reparse: bool = Query(False),
):
    svc = get_super_agent_service()
    run = svc.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Super Agent run 不存在: {run_id}")

    existing = dict(run.phase_artifacts.get("parse_preview_job") or {})
    if (
        not force_reparse
        and _parse_preview_job_is_active(existing)
        and _parse_preview_job_recently_updated(str(existing.get("updated_at") or ""))
    ):
        return success_response({"job": existing, "reused": True})

    job_id = f"ppj_{uuid.uuid4().hex[:12]}"
    try:
        job = _set_parse_preview_job(
            run_id,
            job_id,
            status="queued",
            progress=5,
            message="解析预览任务已排队",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    background_tasks.add_task(_execute_parse_preview_background, run_id, job_id, force_reparse)
    return success_response({"job": job})


@router.get(
    "/runs/{run_id}/parse-preview/jobs/{job_id}",
    summary="查询后台解析预览任务状态（步骤 3）",
)
def get_parse_preview_job(run_id: str, job_id: str):
    svc = get_super_agent_service()
    run = svc.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Super Agent run 不存在: {run_id}")
    job = dict(run.phase_artifacts.get("parse_preview_job") or {})
    if not job or job.get("job_id") != job_id:
        raise HTTPException(status_code=404, detail=f"解析预览任务不存在: {job_id}")
    run_payload = run.model_dump(mode="json")
    run_payload.pop("parse_preview", None)
    payload = {
        "job": job,
        "run": run_payload,
    }
    if job.get("status") == "completed":
        payload["preview"] = run.parse_preview
    return success_response(payload)


@router.post(
    "/runs/{run_id}/parse",
    summary="独立执行文档解析（document_parse）",
    description=(
        "基于 run 已保存的材料与识别结果产出 parse-only artifact；"
        "`include_structure=true` 时在同一 parse artifact 上构建 structure，不依赖 review。"
    ),
)
def parse_run(run_id: str, req: SuperAgentParseRunRequest | None = None):
    svc = get_super_agent_service()
    try:
        result = svc.parse_run(run_id, req)
        run = svc.get_run(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return success_response(
        {
            **result.model_dump(mode="json"),
            "run": run.model_dump(mode="json") if run else {},
        }
    )


@router.post(
    "/runs/{run_id}/review",
    summary="独立执行文档审查（document_review）",
    description=(
        "基于 run 已有 parse artifact 执行 Review-Plus / GNC / skill 审查；"
        "默认 `skip_reparse=true` 复用已有 parse artifact，不强制重新 parse。"
    ),
)
def review_run(
    run_id: str,
    background_tasks: BackgroundTasks,
    req: SuperAgentReviewRunRequest | None = None,
):
    svc = get_super_agent_service()
    try:
        run = svc.prepare_review_run(run_id, req)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    background_tasks.add_task(_execute_super_agent_review_background, run_id, req)
    return success_response(run.model_dump(mode="json"))


@router.get(
    "/runs/{run_id}/materials/source",
    summary="下载 Run 中已上传的原始材料（供解析预览左侧 PDF 浏览）",
)
def download_run_material_source(run_id: str, file_name: str = Query(..., min_length=1)):
    import mimetypes

    svc = get_super_agent_service()
    try:
        path, resolved_name = svc.resolve_run_material_source(run_id, file_name)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    media_type = mimetypes.guess_type(resolved_name)[0] or "application/octet-stream"
    return FileResponse(path, media_type=media_type, filename=resolved_name)


@router.get(
    "/runs/{run_id}/materials/figures",
    summary="获取 parse-preview 中 figure 块的裁剪原图",
)
def download_run_material_figure(
    run_id: str,
    file_name: str = Query(..., min_length=1),
    block_id: str = Query(..., min_length=1),
):
    svc = get_super_agent_service()
    try:
        path = svc.resolve_run_material_figure(run_id, file_name, block_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(path, media_type="image/jpeg", filename=path.name)


@router.get(
    "/runs",
    summary="分页列出 Super Agent Run",
)
def list_runs(page: int = Query(1, ge=1), size: int = Query(20, ge=1, le=100)):
    runs = get_super_agent_service().list_runs()
    total = len(runs)
    start = (page - 1) * size
    page_runs = runs[start : start + size]
    return paginated_response(
        [run.model_dump(mode="json") for run in page_runs],
        page=page,
        size=size,
        total=total,
    )


@router.get(
    "/runs/{run_id}",
    summary="获取 Super Agent Run 详情",
)
def get_run(run_id: str):
    try:
        run = get_super_agent_service().get_run(run_id)
    except Exception as exc:
        logger.exception("[SuperAgent] get_run failed for %s", run_id)
        raise HTTPException(status_code=500, detail=f"读取 Super Agent run 失败: {exc}") from exc
    if not run:
        raise HTTPException(status_code=404, detail=f"Super Agent run 不存在: {run_id}")
    return success_response(run.model_dump(mode="json"))


@router.delete(
    "/runs/{run_id}",
    summary="删除 Super Agent Run（级联 Review-Plus / GNC / 上传文件）",
)
def delete_run(run_id: str, force: bool = Query(False)):
    svc = get_super_agent_service()
    try:
        result = svc.delete_run(run_id, force=force)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not result.get("deleted"):
        raise HTTPException(status_code=404, detail=f"Super Agent run 不存在: {run_id}")
    return success_response(result)


@router.post(
    "/runs/{run_id}/execute",
    summary="执行已创建的 Run",
)
def execute_run(run_id: str):
    try:
        run = get_super_agent_service().execute_run(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _run_response(run)


@router.post(
    "/runs/{run_id}/execute/gnc",
    summary="按 GNC 审查模式执行 Run",
)
def execute_gnc_run(
    run_id: str,
    review_mode: SuperAgentReviewMode = Query(SuperAgentReviewMode.FULL),
):
    svc = get_super_agent_service()
    run = svc.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Super Agent run 不存在: {run_id}")
    req = CreateSuperAgentRunRequest(
        name=run.name,
        objective=run.objective,
        processing_mode=run.processing_mode,
        input_mode=run.input_mode,
        source_review_id=run.source_review_id,
        requested_route=run.requested_route,
        review_mode=review_mode,
        materials=run.materials,
        execute=True,
    )
    try:
        run = svc.execute_run(run_id, request=req)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _run_response(run)


@router.get(
    "/runs/{run_id}/gnc/status",
    summary="获取 GNC 审查状态",
)
def get_gnc_status(run_id: str):
    run = get_super_agent_service().get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Super Agent run 不存在: {run_id}")
    result = run.gnc_review_result or {}
    return success_response(
        {
            "run_id": run.run_id,
            "review_mode": run.review_mode.value,
            "gnc_review_id": (
                run.route_decision.gnc_review_id
                if run.route_decision and run.route_decision.gnc_review_id
                else result.get("gnc_review_id") or result.get("review_id") or ""
            ),
            "status": result.get("status") or "not_started",
            "reason": result.get("reason", ""),
        }
    )


@router.get(
    "/runs/{run_id}/gnc/result",
    summary="获取 GNC 审查结果",
)
def get_gnc_result(run_id: str):
    run = get_super_agent_service().get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Super Agent run 不存在: {run_id}")
    return success_response(run.gnc_review_result)


@router.post(
    "/classify",
    summary="上传材料并返回 L0/L1 自动分类（步骤 2 智能识别）",
)
async def classify_materials(files: list[UploadFile] = File(...)):
    import tempfile
    from pathlib import Path

    from data_agent.parsing.material_preview import extract_material_preview

    svc = get_super_agent_service()
    materials: list[dict[str, str]] = []
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        for file in files:
            raw = await file.read()
            safe_name = (file.filename or "未知").strip() or "未知"
            file_path = tmp_path / safe_name
            file_path.write_bytes(raw or b"")
            preview = extract_material_preview(str(file_path), safe_name)
            materials.append(
                {
                    "filename": safe_name,
                    "file_name": safe_name,
                    "content_preview": preview,
                    "content": preview,
                }
            )
    if not materials:
        raise HTTPException(status_code=400, detail="请至少上传一个文件")
    from data_agent.super_agent.schemas import SuperAgentRun

    try:
        classification = await asyncio.to_thread(svc._classify_materials, SuperAgentRun(), materials)
    except Exception as exc:
        logger.exception("[SuperAgent] classify_materials upload failed")
        raise HTTPException(status_code=500, detail=f"材料识别失败: {exc}") from exc
    return success_response(classification)


@router.post(
    "/parse-preview",
    summary="上传材料并返回分级解析预览（解析确认步骤）",
)
async def parse_preview_materials(
    files: list[UploadFile] = File(...),
    objective: str = Form(""),
    processing_mode: str = Form("OPTIMAL"),
    parser_type: str = Form("auto"),
    mineru_parse_mode: str = Form(""),
    known_classification_json: str = Form(""),
):
    svc = get_super_agent_service()
    uploads: list[tuple[str, bytes]] = []
    for file in files:
        raw = await file.read()
        uploads.append((file.filename or "未知", raw))
    if not uploads:
        raise HTTPException(status_code=400, detail="请至少上传一个文件")
    known_classification: dict | None = None
    if known_classification_json.strip():
        try:
            import json

            parsed = json.loads(known_classification_json)
            if isinstance(parsed, dict):
                known_classification = parsed
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail="known_classification_json 不是合法 JSON") from exc
    try:
        preview = await asyncio.to_thread(
            svc.preview_parse_materials,
            uploads,
            objective=objective,
            processing_mode=processing_mode,
            parser_type=parser_type,
            mineru_parse_mode=mineru_parse_mode,
            known_classification=known_classification,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return success_response(preview)


@router.get(
    "/runs/{run_id}/traces",
    summary="获取 trace 与五维质量评分",
)
def get_traces(run_id: str):
    svc = get_super_agent_service()
    run = svc.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Super Agent run 不存在: {run_id}")
    run.trace_report = svc.collect_traces(run)
    run.quality_report = svc.evaluate_quality(run)
    return success_response(
        {
            "trace_report": run.trace_report.model_dump(mode="json"),
            "quality_report": run.quality_report.model_dump(mode="json"),
            "skill_traces": [trace.model_dump(mode="json") for trace in run.skill_traces],
        }
    )
