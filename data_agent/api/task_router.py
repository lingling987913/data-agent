from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status

from data_agent.api.access_control import is_internal_request, is_public_exposure_scope
from data_agent.api.auth import verify_api_token
from data_agent.api.schemas import TaskSubmitRequest, TaskSubmitResponse, TaskStatusResponse
from data_agent.core.contracts import error_response, success_response
from data_agent.core.task_queue import TaskStatus, get_task_queue
from data_agent.services.document_task_service import run_document_task

router = APIRouter(prefix="/api/v1/task", tags=["competition-task"])


@router.post(
    "/submit",
    summary="提交竞赛任务",
    description=(
        "提交文档（单 PDF 或文档包）并异步执行解析与 Review-Plus 审查。"
        " 返回 `task_id` 用于轮询状态与获取结果。"
    ),
)
async def submit_task(
    body: TaskSubmitRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    _: None = Depends(verify_api_token),
):
    if not body.documents:
        return error_response(message="documents is required", code=400)

    if is_public_exposure_scope() and not is_internal_request(request):
        blocked = [
            d.file_name
            for d in body.documents
            if d.content_type in {"path", "url"}
        ]
        if blocked:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "content_type path/url is not allowed on the public competition API; "
                    "use base64. Internal clients may use path from private networks."
                ),
            )

    queue = get_task_queue()
    task = queue.create_task(
        task_description=body.task_description,
        documents=[d.model_dump() for d in body.documents],
        processing_mode=body.processing_mode,
        output_format=body.output_format,
        output_schema=body.output_schema,
        package_id=body.package_id,
        use_dag=body.use_dag,
    )
    background_tasks.add_task(queue.execute_task, task.task_id, run_document_task)
    return success_response(
        TaskSubmitResponse(
            task_id=task.task_id,
            status="pending",
            created_at=task.created_at,
        ).model_dump()
    )


@router.get(
    "/status/{task_id}",
    summary="查询任务状态",
    description="返回任务进度、当前步骤、场景识别与解析器轨迹。",
)
async def get_task_status(
    task_id: str,
    _: None = Depends(verify_api_token),
):
    queue = get_task_queue()
    payload = queue.get_status(task_id)
    if not payload:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found")
    return success_response(TaskStatusResponse(**payload).model_dump())


@router.get(
    "/result/{task_id}",
    summary="获取任务结果",
    description="任务完成后返回结构化审查结果；未完成时返回 409。",
)
async def get_task_result(
    task_id: str,
    _: None = Depends(verify_api_token),
):
    queue = get_task_queue()
    payload = queue.get_result(task_id)
    if not payload:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found")
    if payload.get("status") not in {TaskStatus.COMPLETED.value, TaskStatus.FAILED.value}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="task not completed yet",
        )
    return success_response(payload)
