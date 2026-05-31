"""Review-Plus material parser router.

The router keeps parser choice and fallback trace visible to downstream review
steps. MinerU online routing follows ``MINERU_API_MODE`` (v4 extract / Agent);
local HTTP is optional second tier.
"""

from __future__ import annotations

import logging
from time import perf_counter

from data_agent.parsing.application_service import ParseDocumentCommand, parse_document
from data_agent.parsing.ingestion import UploadedMaterialParseResult
from data_agent.parsing.material_parser_route import resolve_material_parser_route
from data_agent.parsing.schemas import ParsedDocument

logger = logging.getLogger(__name__)


def _trace_entry(parser: str, status: str, *, elapsed_ms: int = 0, warning: str = "") -> dict:
    return {
        "parser": parser,
        "status": status,
        "elapsed_ms": elapsed_ms,
        "warning": warning,
    }


def _ingest_with_trace(
    file_path: str,
    file_name: str,
    parser_type: str,
    processing_mode: str | None = None,
) -> tuple[UploadedMaterialParseResult, dict]:
    start = perf_counter()
    payload = parse_document(
        ParseDocumentCommand(
            file_path=file_path,
            file_name=file_name,
            parser_type=parser_type,
            processing_mode=processing_mode,
            include_document=True,
            include_artifact=False,
        )
    )
    document_payload = payload.get("document")
    parsed_document = ParsedDocument.model_validate(document_payload) if document_payload else None
    parsed = UploadedMaterialParseResult(
        file_type=str(payload.get("file_type") or ""),
        content=str(payload.get("content") or ""),
        parse_status=str(payload.get("parse_status") or "failed"),
        parser_name=str(payload.get("parser_name") or parser_type),
        warnings=list(payload.get("warnings") or []),
        parsed_document=parsed_document,
        parser_fallback_logs=list(payload.get("parser_fallback_logs") or []),
        self_healing_records=list(payload.get("self_healing_records") or []),
    )
    elapsed_ms = int((perf_counter() - start) * 1000)
    warning = "; ".join(parsed.warnings[:3])
    return parsed, _trace_entry(parsed.parser_name or parser_type, parsed.parse_status, elapsed_ms=elapsed_ms, warning=warning)


def _build_parser_trace(parsed: UploadedMaterialParseResult, trace: dict) -> list[dict]:
    traces = [trace]
    for item in parsed.parser_fallback_logs or []:
        traces.append({**item, "kind": "parser_fallback"})
    for item in parsed.self_healing_records or []:
        traces.append({**item, "kind": "self_healing"})
    return traces


def parse_review_plus_material(
    file_path: str,
    file_name: str,
    *,
    parser_type: str = "auto",
    processing_mode: str | None = None,
) -> tuple[UploadedMaterialParseResult, list[dict]]:
    """Parse a review-plus material with visible parser routing and fallback."""
    route = resolve_material_parser_route(file_name, parser_type, processing_mode)
    parsed, trace = _ingest_with_trace(
        file_path,
        file_name,
        route.parser_type,
        route.processing_mode,
    )
    if route.warning:
        parsed.warnings.append(route.warning)
    trace = {
        **trace,
        "route_reason": route.reason,
        "requested_parser_type": (parser_type or "auto").strip().lower(),
    }
    if parser_type == "mineru_via_pdf":
        parsed.warnings.append("mineru_via_pdf 已合并为 MinerU 联网解析。")
    return parsed, _build_parser_trace(parsed, trace)
