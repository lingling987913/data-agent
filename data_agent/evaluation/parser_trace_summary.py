from __future__ import annotations

from typing import Any

PARSER_TRACE_SUMMARY_KEYS = (
    "file_results",
    "batch_summary",
    "parser_fallback_logs",
    "parser_traces",
    "skill_traces",
)


def build_parser_trace_summary(
    *,
    parse_artifact: dict[str, Any] | None = None,
    parser_fallback_logs: list[dict[str, Any]] | None = None,
    parser_traces: list[dict[str, Any]] | None = None,
    skill_traces: list[Any] | None = None,
) -> dict[str, Any]:
    """Normalize parser / parse_artifact / skill trace fields for Planning and Task outputs."""
    artifact = parse_artifact or {}
    file_results = list(artifact.get("file_results") or [])
    batch_summary = dict(artifact.get("batch_summary") or {})

    fallback_logs = list(parser_fallback_logs or [])
    if not fallback_logs:
        for item in file_results:
            for event in item.get("parser_fallback_logs") or []:
                if isinstance(event, dict):
                    fallback_logs.append(dict(event))

    traces = list(parser_traces or [])
    if not traces and file_results:
        for item in file_results:
            traces.append(
                {
                    "parser": item.get("parser_selected") or "",
                    "status": item.get("parse_status") or "failed",
                    "file_name": item.get("file_name") or "",
                }
            )

    skills: list[dict[str, Any]] = []
    for item in skill_traces or []:
        if hasattr(item, "model_dump"):
            skills.append(item.model_dump(mode="json"))
        elif isinstance(item, dict):
            skills.append(dict(item))

    return {
        "file_results": file_results,
        "batch_summary": batch_summary,
        "parser_fallback_logs": fallback_logs,
        "parser_traces": traces,
        "skill_traces": skills,
    }
