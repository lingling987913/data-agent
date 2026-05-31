"""REST API for document structuring / self-healing."""

from __future__ import annotations

import base64
import logging
import os
import tempfile
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from data_agent.api.auth import verify_api_token
from data_agent.api.structuring_schemas import (
    HealBlocksRequest,
    ModeInfo,
    StructuringHealRequest,
    StructuringHealResponse,
    StructuringModesResponse,
)
from data_agent.core.config import PROJECT_ROOT, UPLOAD_DIR, get_structuring_processing_mode, is_structuring_enabled
from data_agent.core.contracts import success_response
from data_agent.parsing.schemas import ParsedDocument
from data_agent.parsing.application_service import ParseDocumentCommand, parse_document
from data_agent.parsing.ingestion import parsed_document_to_markdown
from data_agent.agents.format_guard.mode_policy import resolve_mode
from data_agent.agents.format_guard.pipeline import SelfHealingPipeline

logger = logging.getLogger(__name__)


def _upload_root() -> Path:
    custom = os.getenv("DATA_AGENT_UPLOAD_DIR", "").strip()
    root = Path(custom) if custom else UPLOAD_DIR
    if not root.is_absolute():
        root = PROJECT_ROOT / root
    return root.resolve()


def _resolve_allowed_upload_path(path_str: str) -> Path:
    """Resolve path and ensure it stays under the upload directory."""
    file_path = Path(path_str).resolve()
    upload_root = _upload_root()
    try:
        file_path.relative_to(upload_root)
    except ValueError as exc:
        raise HTTPException(
            status_code=403,
            detail="Path access denied: file must be under upload directory",
        ) from exc
    if not file_path.is_file():
        raise HTTPException(status_code=422, detail=f"File not found: {file_path}")
    return file_path


router = APIRouter(
    prefix="/api/v1/structuring",
    tags=["structuring"],
    dependencies=[Depends(verify_api_token)],
)


@router.get("/modes", summary="列出结构化自愈三态模式")
async def list_modes():
    default_mode = get_structuring_processing_mode()
    modes = []
    for mode, desc in (
        ("HIGH_ACCURACY", "全量 MinerU 降级链 + 全量 Repair/指代消解"),
        ("HIGH_SPEED", "本地解析，仅 FormatDetector，不调用 LLM"),
        ("OPTIMAL", "自动解析 + 仅损坏块 Repair + 规则命中指代消解"),
    ):
        policy = resolve_mode(mode)
        modes.append(
            ModeInfo(
                mode=mode,
                parser_type=policy.parser_type,
                run_repair_llm=policy.run_repair_llm,
                run_anaphora_llm=policy.run_anaphora_llm,
                description=desc,
            )
        )
    payload = StructuringModesResponse(default_mode=default_mode, modes=modes)
    return success_response(payload.model_dump(mode="json"))


@router.post("/heal", summary="上传内容并执行解析 + 自愈")
async def heal_document(req: StructuringHealRequest):
    if not is_structuring_enabled():
        raise HTTPException(status_code=503, detail="Structuring is disabled")

    policy = resolve_mode(req.processing_mode)
    parser_type = (req.parser_type or policy.parser_type).strip() or "local"

    tmp_path: str | None = None
    try:
        if req.content_type == "base64":
            try:
                raw = base64.b64decode(req.content, validate=True)
            except Exception as exc:
                raise HTTPException(status_code=422, detail="Invalid base64 content") from exc
            suffix = os.path.splitext(req.file_name)[1] or ".md"
            fd, tmp_path = tempfile.mkstemp(suffix=suffix)
            with os.fdopen(fd, "wb") as f:
                f.write(raw)
            file_path = tmp_path
        else:
            file_path = str(_resolve_allowed_upload_path(req.content))

        parsed_payload = parse_document(
            ParseDocumentCommand(
                file_path=file_path,
                file_name=req.file_name,
                parser_type=parser_type,
                processing_mode=req.processing_mode,
                include_document=True,
                include_artifact=False,
            )
        )
        document_payload = parsed_payload.get("document")
        if not document_payload:
            raise HTTPException(status_code=422, detail="Document parsing did not produce ParsedDocument")
        parsed_doc = ParsedDocument.model_validate(document_payload)
        pipeline = SelfHealingPipeline()
        result = await pipeline.run(parsed_doc, processing_mode=req.processing_mode)
        markdown = parsed_document_to_markdown(result.document)
        section_tree = result.section_tree if req.build_section_tree else None
        response = StructuringHealResponse(
            document=result.document,
            markdown=markdown,
            section_tree=section_tree,
            result=result,
        )
        return success_response(response.model_dump(mode="json"))
    finally:
        if tmp_path and os.path.isfile(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                logger.debug("failed to remove temp file %s", tmp_path)


@router.post("/heal-blocks", summary="对已有 blocks JSON 执行自愈（调试）")
async def heal_blocks(req: HealBlocksRequest):
    if not is_structuring_enabled():
        raise HTTPException(status_code=503, detail="Structuring is disabled")

    document = ParsedDocument(
        document_id=req.document_id or str(uuid.uuid4()),
        file_name=req.file_name,
        file_type="design_report",
        parser_name="inline_blocks",
        parse_status="ok",
        blocks=req.blocks,
    )
    pipeline = SelfHealingPipeline()
    result = await pipeline.run(document, processing_mode=req.processing_mode)
    markdown = parsed_document_to_markdown(result.document)
    response = StructuringHealResponse(
        document=result.document,
        markdown=markdown,
        section_tree=result.section_tree,
        result=result,
    )
    return success_response(response.model_dump(mode="json"))
