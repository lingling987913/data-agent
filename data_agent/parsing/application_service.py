"""Public parsing application service.

This service is the stable boundary for standalone document parsing. It is
intended for API routers, Task API, and future external consumers. Review and
structuring workflows should consume its artifact-shaped output instead of
calling low-level parser functions directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from data_agent.evaluation.parser_trace_summary import build_parser_trace_summary


@dataclass(frozen=True)
class ParseDocumentCommand:
    file_path: str
    file_name: str
    parser_type: str = "auto"
    processing_mode: str | None = "OPTIMAL"
    mineru_parse_mode: str | None = None
    include_document: bool = True
    include_artifact: bool = True
    skip_enhancement: bool = True
    figure_storage_dir: str | None = None


def _parser_trace_from_result(result: Any) -> list[dict[str, Any]]:
    traces: list[dict[str, Any]] = [
        {
            "parser": result.parser_name or "",
            "status": result.parse_status or "failed",
            "file_name": result.file_type or "",
        }
    ]
    for item in result.parser_fallback_logs or []:
        traces.append({**item, "kind": "parser_fallback"})
    for item in result.self_healing_records or []:
        traces.append({**item, "kind": "self_healing"})
    return traces


def _parsed_payload(file_name: str, result: Any) -> dict[str, Any]:
    document = result.parsed_document
    return {
        "file_name": file_name,
        "file_type": result.file_type,
        "parse_status": result.parse_status,
        "parser_name": result.parser_name,
        "block_count": len(document.blocks) if document else 0,
        "content": result.content,
        "warnings": list(result.warnings or []),
        "parser_fallback_logs": list(result.parser_fallback_logs or []),
        "self_healing_records": list(result.self_healing_records or []),
        "document": document.model_dump(mode="json") if document else None,
    }


def parse_document(command: ParseDocumentCommand) -> dict[str, Any]:
    """Parse one document and return a stable, JSON-serializable payload."""
    from data_agent.parsing.ingestion import ingest_uploaded_material

    file_name = command.file_name or Path(command.file_path).name or "material.txt"
    result = ingest_uploaded_material(
        command.file_path,
        file_name,
        parser_type=command.parser_type or "auto",
        processing_mode=command.processing_mode,
        mineru_parse_mode=command.mineru_parse_mode,
        skip_enhancement=command.skip_enhancement,
        figure_storage_dir=command.figure_storage_dir,
    )
    document_payload = _parsed_payload(file_name, result)
    parsed_batch = {
        "parser_used": result.parser_name,
        "blocks": int(document_payload["block_count"]),
        "material_count": 1,
        "warning_count": len(result.warnings or []),
        "documents": [document_payload],
        "document": document_payload.get("document"),
        "parser_fallback_logs": list(result.parser_fallback_logs or []),
    }

    parse_artifact: dict[str, Any] = {}
    if command.include_artifact:
        from data_agent.parsing.parse_artifacts import build_parse_only_artifact_from_parsed

        artifact = build_parse_only_artifact_from_parsed(parsed_batch)
        parse_artifact = artifact.model_dump(mode="json")

    parser_traces = _parser_trace_from_result(result)
    parser_trace_summary = build_parser_trace_summary(
        parse_artifact=parse_artifact,
        parser_fallback_logs=list(result.parser_fallback_logs or []),
        parser_traces=parser_traces,
    )

    payload = {
        "file_name": file_name,
        "file_type": result.file_type,
        "parse_status": result.parse_status,
        "parser_name": result.parser_name,
        "content": result.content,
        "warnings": list(result.warnings or []),
        "parser_traces": parser_traces,
        "parser_fallback_logs": list(result.parser_fallback_logs or []),
        "self_healing_records": list(result.self_healing_records or []),
        "parser_trace_summary": parser_trace_summary,
        "enhancement_skipped": bool(command.skip_enhancement),
    }
    if command.include_document:
        payload["document"] = document_payload.get("document")
    if command.include_artifact:
        payload["parse_artifact"] = parse_artifact
    return payload
