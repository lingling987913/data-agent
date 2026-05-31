"""REST API for standalone document parsing."""

from __future__ import annotations

import base64
import logging
import os
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from data_agent.api.auth import verify_api_token
from data_agent.api.parsing_schemas import ParseDocumentRequest, ParseDocumentResponse
from data_agent.core.config import PROJECT_ROOT, UPLOAD_DIR
from data_agent.core.contracts import success_response
from data_agent.parsing.application_service import ParseDocumentCommand, parse_document

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/parsing",
    tags=["parsing"],
    dependencies=[Depends(verify_api_token)],
)


def _upload_root() -> Path:
    custom = os.getenv("DATA_AGENT_UPLOAD_DIR", "").strip()
    root = Path(custom) if custom else UPLOAD_DIR
    if not root.is_absolute():
        root = PROJECT_ROOT / root
    return root.resolve()


def _resolve_allowed_upload_path(path_str: str) -> Path:
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


@router.post("/parse", summary="独立解析文档并返回解析产物")
async def parse_document_endpoint(req: ParseDocumentRequest):
    tmp_path: str | None = None
    try:
        if req.content_type == "base64":
            try:
                raw = base64.b64decode(req.content, validate=True)
            except Exception as exc:
                raise HTTPException(status_code=422, detail="Invalid base64 content") from exc
            suffix = os.path.splitext(req.file_name)[1] or ".md"
            fd, tmp_path = tempfile.mkstemp(suffix=suffix)
            with os.fdopen(fd, "wb") as handle:
                handle.write(raw)
            file_path = tmp_path
        else:
            file_path = str(_resolve_allowed_upload_path(req.content))

        payload = parse_document(
            ParseDocumentCommand(
                file_path=file_path,
                file_name=req.file_name,
                parser_type=req.parser_type,
                processing_mode=req.processing_mode,
                include_document=req.include_document,
                include_artifact=req.include_artifact,
                skip_enhancement=req.skip_enhancement,
            )
        )
        return success_response(ParseDocumentResponse(**payload).model_dump(mode="json"))
    finally:
        if tmp_path and os.path.isfile(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                logger.debug("failed to remove temp file %s", tmp_path)
