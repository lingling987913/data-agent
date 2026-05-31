"""GNC design-review REST API."""

from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import StreamingResponse

from data_agent.api.auth import verify_api_token
from data_agent.core.config import RUNS_DIR
from data_agent.core.contracts import paginated_response, success_response
from data_agent.review_plus.task_artifact_cleanup import remove_task_artifacts
from data_agent.integrations.satellite_review.gnc_schemas import (
    GNCReviewRequest,
    GNCReviewRun,
    GNCReviewStatus,
)
from data_agent.integrations.satellite_review.gnc_workflow import run_gnc_design_review
from data_agent.review_workbench.gnc_workbench_service import (
    apply_arbitration,
    build_workbench_detail,
    paginate_events,
    patch_rid_item,
    project_committee,
    project_decision,
    project_evidences,
    project_findings,
    project_minutes,
    project_rid_items,
)
from data_agent.review_workbench.schemas import GNCArbitrationRequest, GNCRidPatchRequest

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/gnc-review",
    tags=["gnc-review"],
    dependencies=[Depends(verify_api_token)],
)


def _now() -> str:
    return datetime.now().isoformat()


class GNCReviewService:
    """JSON-backed lifecycle service for migrated GNC reviews."""

    _instance: "GNCReviewService | None" = None
    _lock = threading.RLock()
    _DATA_DIR = RUNS_DIR / "gnc_tasks"

    def __new__(cls) -> "GNCReviewService":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._store = {}
            cls._instance._sequence_store = {}
            cls._instance._load_all()
        return cls._instance

    def _path(self, review_id: str) -> Path:
        return self._DATA_DIR / f"{review_id}.json"

    def _save(self, run: GNCReviewRun) -> None:
        self._DATA_DIR.mkdir(parents=True, exist_ok=True)
        with self._lock:
            run.updated_at = _now()
            self._store[run.review_id] = run
            self._path(run.review_id).write_text(run.model_dump_json(indent=2), encoding="utf-8")

    def _load_all(self) -> None:
        self._store = {}
        self._sequence_store = {}
        if not self._DATA_DIR.exists():
            return
        for path in self._DATA_DIR.glob("*.json"):
            try:
                run = GNCReviewRun.model_validate(json.loads(path.read_text(encoding="utf-8")))
                self._store[run.review_id] = run
                self._sequence_store[run.review_id] = max(
                    (int(event.get("sequence", 0)) for event in run.events if isinstance(event, dict)),
                    default=0,
                )
            except Exception as exc:
                logger.warning("[GNC-Review] failed to load %s: %s", path.name, exc)

    def create_review(self, request: GNCReviewRequest) -> GNCReviewRun:
        run = GNCReviewRun(
            name=request.name,
            request=request,
            status=GNCReviewStatus.READY,
        )
        self._save(run)
        self.record_event(run.review_id, "task_created", {"name": run.name, "mode": request.mode.value})
        return run

    def get_review(self, review_id: str) -> GNCReviewRun | None:
        with self._lock:
            return self._store.get(review_id)

    def record_event(self, review_id: str, event_type: str, payload: dict | None = None) -> dict:
        with self._lock:
            run = self.get_review(review_id)
            if not run:
                return {}
            sequence = self._sequence_store.get(review_id, 0) + 1
            self._sequence_store[review_id] = sequence
            event = {
                "sequence": sequence,
                "type": event_type,
                "payload": payload or {},
                "created_at": _now(),
            }
            run.events.append(event)
            self._save(run)
            return event

    def start_review(self, review_id: str) -> GNCReviewRun:
        run = self.get_review(review_id)
        if not run:
            raise KeyError(f"GNC review task not found: {review_id}")
        if run.status == GNCReviewStatus.RUNNING:
            raise ValueError(f"GNC review task is already running: {review_id}")
        if run.status in {GNCReviewStatus.COMPLETED, GNCReviewStatus.ARBITRATION_PENDING}:
            return run

        run.status = GNCReviewStatus.RUNNING
        run.current_step = "review_intake"
        run.error = ""
        self._save(run)
        self.record_event(review_id, "review_started", {"status": run.status.value})
        # TODO(phase-2): incrementally persist step_outputs + events per workflow step
        # inside background execution. Requires workflow callback/hook support; defer to
        # avoid risky changes to run_gnc_design_review's monolithic execution model.
        try:
            result, step_outputs = run_gnc_design_review(run.request, review_id=review_id)
        except Exception as exc:
            run = self.get_review(review_id) or run
            run.status = GNCReviewStatus.FAILED
            run.error = str(exc)
            run.current_step = "failed"
            self._save(run)
            self.record_event(review_id, "review_failed", {"error": str(exc)})
            raise

        run = self.get_review(review_id) or run
        run.result = result
        run.step_outputs = step_outputs
        run.current_step = "review_closure"
        run.status = result.status
        self._save(run)
        self.record_event(review_id, "review_completed", {"status": run.status.value})
        return run

    def get_events(self, review_id: str) -> list[dict] | None:
        run = self.get_review(review_id)
        return None if not run else list(run.events)

    def save_run(self, run: GNCReviewRun) -> GNCReviewRun:
        self._save(run)
        return run

    def delete_review(self, review_id: str, *, force: bool = False) -> dict:
        with self._lock:
            run = self._store.get(review_id)
        if not run:
            path = self._path(review_id)
            removed = remove_task_artifacts(review_id, path) if path.exists() else []
            return {"deleted": bool(removed), "review_id": review_id, "removed_files": removed}

        if (not force) and run.status == GNCReviewStatus.RUNNING:
            raise ValueError("GNC 审查任务正在执行中，不能删除")

        with self._lock:
            self._store.pop(review_id, None)
            self._sequence_store.pop(review_id, None)

        removed_files = remove_task_artifacts(review_id, self._path(review_id))
        logger.info("[GNC-Review] Deleted task: %s, force=%s, removed=%s", review_id, force, len(removed_files))
        return {
            "deleted": True,
            "review_id": review_id,
            "force": force,
            "removed_files": removed_files,
        }


def get_gnc_review_service() -> GNCReviewService:
    return GNCReviewService()


def _not_found(review_id: str) -> None:
    raise HTTPException(status_code=404, detail=f"GNC 审查任务不存在: {review_id}")


@router.post(
    "/create",
    summary="创建 GNC 审查任务",
)
async def create_review(req: GNCReviewRequest):
    run = get_gnc_review_service().create_review(req)
    return success_response(run.model_dump(mode="json"))


@router.post(
    "/{review_id}/start",
    summary="启动 GNC 审查",
)
async def start_review(review_id: str, background_tasks: BackgroundTasks):
    svc = get_gnc_review_service()
    run = svc.get_review(review_id)
    if not run:
        _not_found(review_id)
    if run.status == GNCReviewStatus.RUNNING:
        raise HTTPException(status_code=409, detail="GNC 审查任务正在运行")

    def _run() -> None:
        try:
            svc.start_review(review_id)
        except Exception:
            logger.exception("[GNC-Review] background review failed: %s", review_id)

    background_tasks.add_task(_run)
    svc.record_event(review_id, "review_queued", {})
    return success_response({"review_id": review_id, "status": "queued"})


@router.get(
    "/{review_id}/status",
    summary="查询 GNC 审查状态",
)
async def get_status(review_id: str):
    run = get_gnc_review_service().get_review(review_id)
    if not run:
        _not_found(review_id)
    return success_response(
        {
            "review_id": run.review_id,
            "status": run.status.value if isinstance(run.status, GNCReviewStatus) else run.status,
            "current_step": run.current_step,
            "error": run.error,
            "updated_at": run.updated_at,
        }
    )


@router.get(
    "/{review_id}/result",
    summary="获取 GNC 审查结果",
)
async def get_result(review_id: str):
    run = get_gnc_review_service().get_review(review_id)
    if not run:
        _not_found(review_id)
    if not run.result:
        raise HTTPException(status_code=409, detail=f"GNC 审查尚未完成，当前状态: {run.status}")
    return success_response(run.result.model_dump(mode="json"))


@router.get(
    "/{review_id}",
    summary="获取 GNC 审查工作台详情",
)
async def get_workbench_detail(review_id: str):
    run = get_gnc_review_service().get_review(review_id)
    if not run:
        _not_found(review_id)
    return success_response(build_workbench_detail(run).model_dump(mode="json"))


@router.get(
    "/{review_id}/findings",
    summary="获取 GNC 审查 findings 投影",
)
async def get_workbench_findings(review_id: str):
    run = get_gnc_review_service().get_review(review_id)
    if not run:
        _not_found(review_id)
    return success_response(project_findings(run))


@router.get(
    "/{review_id}/rid",
    summary="获取 GNC 审查 RID 列表投影",
)
async def get_workbench_rid(review_id: str):
    run = get_gnc_review_service().get_review(review_id)
    if not run:
        _not_found(review_id)
    return success_response(project_rid_items(run))


@router.get(
    "/{review_id}/minutes",
    summary="获取 GNC 审查纪要投影",
)
async def get_workbench_minutes(review_id: str):
    run = get_gnc_review_service().get_review(review_id)
    if not run:
        _not_found(review_id)
    return success_response(project_minutes(run))


@router.get(
    "/{review_id}/decision",
    summary="获取 GNC 总师审定结论投影",
)
async def get_workbench_decision(review_id: str):
    run = get_gnc_review_service().get_review(review_id)
    if not run:
        _not_found(review_id)
    return success_response(project_decision(run))


@router.get(
    "/{review_id}/committee",
    summary="获取 GNC 专家组审查投影",
)
async def get_workbench_committee(review_id: str):
    run = get_gnc_review_service().get_review(review_id)
    if not run:
        _not_found(review_id)
    return success_response(project_committee(run))


@router.get(
    "/{review_id}/evidences",
    summary="获取 GNC 证据池投影",
)
async def get_workbench_evidences(review_id: str):
    run = get_gnc_review_service().get_review(review_id)
    if not run:
        _not_found(review_id)
    return success_response(project_evidences(run))


@router.get(
    "/{review_id}/events-page",
    summary="分页获取 GNC 审查事件",
)
async def get_events_page(review_id: str, page: int = 1, size: int = 50):
    svc = get_gnc_review_service()
    run = svc.get_review(review_id)
    if not run:
        _not_found(review_id)
    items, total = paginate_events(list(run.events), page=page, size=size)
    return paginated_response(items, page=page, size=size, total=total)


@router.post(
    "/{review_id}/arbitration",
    summary="提交 GNC 人工仲裁结果",
)
async def submit_arbitration(review_id: str, payload: GNCArbitrationRequest):
    svc = get_gnc_review_service()
    run = svc.get_review(review_id)
    if not run:
        _not_found(review_id)
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
    "/{review_id}/rid/{rid_id}",
    summary="更新 GNC RID 状态或备注",
)
async def patch_workbench_rid(review_id: str, rid_id: str, payload: GNCRidPatchRequest):
    svc = get_gnc_review_service()
    run = svc.get_review(review_id)
    if not run:
        _not_found(review_id)
    if not project_rid_items(run):
        raise HTTPException(status_code=409, detail="当前审查尚无 RID 数据")

    updated = patch_rid_item(run, rid_id, payload)
    if updated is None:
        raise HTTPException(status_code=404, detail=f"RID 不存在: {rid_id}")

    svc.save_run(run)
    svc.record_event(review_id, "rid_updated", {"rid_id": rid_id, "status": updated.get("status")})
    return success_response(updated)


def _sse_terminal_statuses() -> set[GNCReviewStatus]:
    """Statuses that end the SSE stream; arbitration_pending keeps streaming for post-arbitration events."""
    return {GNCReviewStatus.COMPLETED, GNCReviewStatus.FAILED}


def _requires_arbitration_run(run: GNCReviewRun) -> bool:
    status = run.status.value if isinstance(run.status, GNCReviewStatus) else str(run.status)
    if status == GNCReviewStatus.ARBITRATION_PENDING.value:
        return True
    if run.result and isinstance(run.result.chief_decision, dict):
        return bool(run.result.chief_decision.get("requires_arbitration"))
    chief_step = (run.step_outputs or {}).get("chief_adjudication") or {}
    if isinstance(chief_step, dict):
        decision = chief_step.get("chief_decision") or {}
        if isinstance(decision, dict) and decision.get("requires_arbitration"):
            return True
    arbitration = (run.step_outputs or {}).get("human_arbitration") or {}
    return isinstance(arbitration, dict) and bool(arbitration.get("requires_arbitration"))


@router.get(
    "/{review_id}/events",
    summary="获取 GNC 审查 SSE 事件流",
)
async def get_events(review_id: str):
    svc = get_gnc_review_service()
    if not svc.get_review(review_id):
        _not_found(review_id)

    def _stream():
        last_seq = 0
        while True:
            run = svc.get_review(review_id)
            if not run:
                yield "event: error\ndata: {\"error\":\"not_found\"}\n\n"
                return
            for event in run.events:
                seq = int(event.get("sequence", 0))
                if seq > last_seq:
                    last_seq = seq
                    yield f"event: {event.get('type', 'message')}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
            if run.status in _sse_terminal_statuses():
                return
            time.sleep(1)

    return StreamingResponse(_stream(), media_type="text/event-stream")


__all__ = ["get_gnc_review_service", "router"]
