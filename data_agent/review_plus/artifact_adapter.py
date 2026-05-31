"""Adapters for applying shared parse artifacts to Review-Plus tasks."""

from __future__ import annotations

from typing import Any


def _sanitize_text(value: str) -> str:
    return value.replace("\x00", "").strip()


def _block_text(block: dict[str, Any]) -> str:
    from data_agent.super_agent.helpers import _block_full_content

    return _block_full_content(block)


def _sync_materials_from_parse_artifact(task: Any, parse_artifact: dict[str, Any]) -> bool:
    """Copy parsed block text and parse metadata onto Review-Plus materials."""
    parsed_by_name = {
        str(item.get("file_name") or ""): item
        for item in (parse_artifact.get("parsed_documents") or [])
        if isinstance(item, dict)
    }
    if not parsed_by_name:
        return False

    changed = False
    for material in getattr(task, "materials", []) or []:
        item = parsed_by_name.get(material.name)
        if not item:
            continue
        document = item.get("document") if isinstance(item.get("document"), dict) else {}
        content_parts: list[str] = []
        for block in document.get("blocks") or []:
            if not isinstance(block, dict):
                continue
            text = _block_text(block)
            if text:
                content_parts.append(text)
        if content_parts:
            content = _sanitize_text("\n".join(content_parts)[:8000])
            if content and content != str(getattr(material, "content", "") or ""):
                material.content = content
                changed = True
        file_type = str(item.get("file_type") or document.get("file_type") or material.file_type or "")
        if file_type and file_type != material.file_type:
            material.file_type = file_type
            changed = True
        parser_name = str(item.get("parser_name") or document.get("parser_name") or material.parser_name or "")
        if parser_name and parser_name != material.parser_name:
            material.parser_name = parser_name
            changed = True
        parse_status = str(item.get("parse_status") or document.get("parse_status") or "ok")
        if parse_status != material.parse_status:
            material.parse_status = parse_status
            changed = True
        warnings = list(item.get("warnings") or document.get("warnings") or [])
        if warnings != (material.warnings or []):
            material.warnings = warnings
            changed = True
        parser_trace = list(item.get("parser_fallback_logs") or []) or material.parser_trace
        if parser_trace != (material.parser_trace or []):
            material.parser_trace = parser_trace
            changed = True
    return changed


def apply_parse_artifact_to_task(svc: Any, task: Any, parse_artifact: dict[str, Any]) -> bool:
    """Persist a parse-only artifact onto a Review-Plus task (Step 3 output)."""
    if not isinstance(parse_artifact, dict) or not parse_artifact:
        return False

    parse_payload = dict(parse_artifact)
    parse_payload["pipeline_step"] = "document_parse"
    changed = _sync_materials_from_parse_artifact(task, parse_payload)

    field_map = {
        "parse_artifact": parse_payload,
        "document_ir": dict(parse_payload.get("document_ir") or {}),
    }
    if not getattr(task, "section_tree", None):
        field_map["section_tree"] = {}
    if not getattr(task, "evidence_pool", None):
        field_map["evidence_pool"] = {}
    if not getattr(task, "parsed_documents", None):
        field_map["parsed_documents"] = []
    for field_name, value in field_map.items():
        current = getattr(task, field_name, None)
        if current != value:
            setattr(task, field_name, value)
            changed = True

    parser_traces = [
        trace
        for material in getattr(task, "materials", []) or []
        for trace in (material.parser_trace or [])
    ]
    if parser_traces != (getattr(task, "parser_traces", None) or []):
        task.parser_traces = parser_traces
        changed = True

    if changed:
        from datetime import datetime

        task.updated_at = datetime.now().isoformat()
        svc._save_task(task)
    return changed


def apply_structured_bundle_to_task(svc: Any, task: Any, structured_bundle: Any) -> bool:
    """Persist a shared structured bundle onto a Review-Plus task.

    The Super Agent and other orchestrators should use this adapter instead of
    mutating Review-Plus task internals directly.
    """
    bundle = (
        structured_bundle.model_dump(mode="json")
        if hasattr(structured_bundle, "model_dump")
        else dict(structured_bundle or {})
    )
    parse_artifact = dict(bundle.get("parse_artifact") or {})
    section_tree = bundle.get("section_tree") or {}
    evidence_pool = bundle.get("evidence_pool") or {}
    if parse_artifact and not (section_tree and evidence_pool):
        return apply_parse_artifact_to_task(svc, task, parse_artifact)

    if not section_tree or not evidence_pool:
        return False

    changed = False
    if parse_artifact:
        changed = _sync_materials_from_parse_artifact(task, parse_artifact) or changed

    field_map = {
        "section_tree": section_tree,
        "evidence_pool": evidence_pool,
        "parsed_documents": list(bundle.get("chunks") or []),
        "document_ir": dict(bundle.get("document_ir") or {}),
        "parse_artifact": parse_artifact,
    }
    for field_name, value in field_map.items():
        if not value:
            continue
        current = getattr(task, field_name, None)
        if current != value:
            setattr(task, field_name, value)
            changed = True

    if changed:
        from datetime import datetime

        task.updated_at = datetime.now().isoformat()
        svc._save_task(task)
    return changed
