"""Shared helpers for Super Agent phase handlers."""

from __future__ import annotations

import base64
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from data_agent.core.config import SUPER_AGENT_UPLOAD_DIR
from data_agent.super_agent.schemas import SuperAgentMaterial

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now().isoformat()


def _parse_iso_timestamp(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _role_value(value: Any) -> str:
    return value.value if hasattr(value, "value") else str(value or "")


def _summarize_task_materials(task: Any) -> list[dict[str, Any]]:
    return [
        {
            "name": getattr(material, "name", ""),
            "file_type": getattr(material, "file_type", ""),
            "parser_type": getattr(material, "parser_type", ""),
            "parser_name": getattr(material, "parser_name", ""),
            "parse_status": getattr(material, "parse_status", ""),
            "role": _role_value(getattr(material, "role", "")),
            "role_confidence": getattr(material, "role_confidence", 0.0),
            "document_version": getattr(material, "document_version", ""),
            "baseline_id": getattr(material, "baseline_id", ""),
            "included_in_formal_review": getattr(material, "included_in_formal_review", True),
        }
        for material in getattr(task, "materials", []) or []
    ]


def _parse_llm_json(content: Any) -> dict[str, Any]:
    if isinstance(content, dict):
        return content
    text = str(getattr(content, "content", content) or "").strip()
    if text.startswith("```"):
        text = "\n".join(line for line in text.splitlines() if not line.strip().startswith("```")).strip()
    if not text:
        raise ValueError("empty LLM response")
    return json.loads(text)


_PARSE_CONTENT_PREVIEW_MAX_CHARS = 2000
_PARSE_CONTENT_MARKDOWN_MAX_CHARS = 8000
_PARSE_PREVIEW_BLOCKS_MAX = 200


def _html_table_preview_text(html: str, *, max_cells: int = 24) -> str:
    import re

    cells = [cell.strip() for cell in re.findall(r">([^<]+)<", html) if cell.strip()]
    if not cells:
        return "[表格]"
    if len(cells) <= max_cells:
        return " | ".join(cells)
    return " | ".join(cells[:max_cells]) + " …"


def _block_to_markdown(block: dict[str, Any], *, use_full_content: bool = False) -> str:
    from data_agent.parsing.math_delimiters import ensure_math_delimiters

    block_type = str(block.get("block_type") or "paragraph")
    text = _block_full_content(block) if use_full_content else _block_display_text(block)
    if not text:
        return ""
    if block_type == "heading":
        level = int(block.get("level") or 2)
        level = min(max(level, 1), 6)
        return f"{'#' * level} {text.strip()}"
    if block_type == "list_item":
        return f"- {text.strip()}"
    if block_type == "formula":
        body = _block_full_content(block)
        if not body:
            return ""
        return f"$$\n{body}\n$$"
    return ensure_math_delimiters(text.strip())


def _serialize_preview_blocks(
    blocks: list[dict[str, Any]],
    *,
    max_blocks: int = _PARSE_PREVIEW_BLOCKS_MAX,
    calibration_records: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    serialized: list[dict[str, Any]] = []
    calibration_by_block: dict[str, list[dict[str, Any]]] = {}
    for record in calibration_records or []:
        if not isinstance(record, dict):
            continue
        block_id = str(record.get("block_id") or "")
        if not block_id:
            continue
        calibration_by_block.setdefault(block_id, []).append(record)
    for block in blocks[:max_blocks]:
        if not isinstance(block, dict):
            continue
        block_type = str(block.get("block_type") or "paragraph")
        block_id = str(block.get("block_id") or "")
        content = _block_full_content(block)
        if not content and block_type not in {"page_break", "figure", "figure_caption", "formula"}:
            continue
        page_hint = block.get("page_hint")
        serialized.append(
            {
                "id": block_id,
                "block_type": block_type,
                "content": content,
                "markdown": _block_to_markdown(block, use_full_content=True),
                "page_hint": int(page_hint) if page_hint is not None else None,
                "bbox": block.get("bbox") if isinstance(block.get("bbox"), list) else None,
                "level": block.get("level"),
                "angle": _block_angle(block),
                "formula_latex": str(block.get("formula_latex") or "").strip() or None,
                "caption": str(block.get("caption") or "").strip() or None,
                "image_description": str(block.get("vision_description") or "").strip() or None,
                "image_ref": str(block.get("image_ref") or "").strip() or None,
                "calibration_records": calibration_by_block.get(block_id, []),
            }
        )
    return serialized


def _build_parse_artifact_subset(
    parsed_item: dict[str, Any],
    file_result: dict[str, Any],
) -> dict[str, Any]:
    document = parsed_item.get("document") if isinstance(parsed_item.get("document"), dict) else {}
    return {
        "file_name": str(parsed_item.get("file_name") or file_result.get("file_name") or ""),
        "parse_status": str(
            file_result.get("parse_status") or parsed_item.get("parse_status") or ""
        ),
        "parser_name": str(
            file_result.get("parser_selected") or parsed_item.get("parser_name") or ""
        ),
        "document_ir_stats": file_result.get("document_ir_stats") or {},
        "capability_passed": file_result.get("capability_passed"),
        "degraded": file_result.get("degraded"),
        "warnings": list(file_result.get("warnings") or document.get("warnings") or []),
        "document_id": str(document.get("document_id") or ""),
    }


def _build_markdown_from_blocks(blocks: list[dict[str, Any]], *, max_chars: int) -> tuple[str, bool]:
    parts: list[str] = []
    total_len = 0
    truncated = False
    for block in blocks:
        if not isinstance(block, dict):
            continue
        segment = _block_to_markdown(block)
        if not segment:
            continue
        if total_len + len(segment) + 2 > max_chars:
            remaining = max_chars - total_len
            if remaining > 0:
                parts.append(segment[:remaining])
            truncated = True
            break
        parts.append(segment)
        total_len += len(segment) + 2
    return "\n\n".join(parts), truncated


def _block_angle(block: dict[str, Any]) -> int | None:
    raw = block.get("angle")
    if raw is None:
        return None
    try:
        angle = int(raw) % 360
    except (TypeError, ValueError):
        return None
    return angle if angle in {0, 90, 180, 270} else None


def _block_full_content(block: dict[str, Any]) -> str:
    """Full block text for per-block preview (layout / block panes)."""
    block_type = str(block.get("block_type") or "paragraph").lower()
    if block_type in {"figure", "image", "figure_caption"}:
        vision = str(block.get("vision_description") or "").strip()
        if vision:
            return vision
        caption = str(block.get("caption") or "").strip()
        if caption:
            return caption
    table_md = str(block.get("table_markdown") or "").strip()
    if table_md:
        return table_md
    formula_latex = str(block.get("formula_latex") or "").strip()
    if formula_latex:
        return formula_latex
    text = str(block.get("text") or "").strip()
    if text == "[figure]":
        return ""
    from data_agent.parsing.figure_text import looks_like_image_ref

    if looks_like_image_ref(text):
        return ""
    return text


def _block_display_text(block: dict[str, Any]) -> str:
    table_md = str(block.get("table_markdown") or "").strip()
    if table_md:
        return table_md
    text = str(block.get("text") or "").strip()
    if not text:
        return ""
    lowered = text.lower()
    if lowered.startswith("<table") and "</table>" in lowered:
        return _html_table_preview_text(text)
    return text


def _material_preview_text(material: SuperAgentMaterial | dict[str, Any], *, max_chars: int = 500) -> str:
    def _preview_from_path(file_path: str, file_name: str = "") -> str:
        if not file_path:
            return ""
        try:
            path = _safe_super_agent_upload_path(file_path)
        except ValueError:
            return ""
        suffix = path.suffix.lower()
        if suffix in {".txt", ".md", ".csv", ".json", ".xml", ".html", ".htm"}:
            try:
                return path.read_text(encoding="utf-8", errors="ignore")[:max_chars]
            except OSError:
                return ""
        try:
            from data_agent.parsing.material_preview import extract_material_preview

            return extract_material_preview(str(path), file_name or path.name)[:max_chars]
        except Exception:
            return ""

    if isinstance(material, SuperAgentMaterial):
        preview = (material.content_preview or "").strip()
        if preview:
            return preview[:max_chars]
        if material.content:
            return material.content[:max_chars]
        if material.file_path:
            return _preview_from_path(material.file_path, material.name)
        return ""
    preview = str(material.get("content_preview") or "").strip()
    if preview:
        return preview[:max_chars]
    content = str(material.get("content") or "")
    if content:
        return content[:max_chars]
    file_path = str(material.get("file_path") or "")
    if file_path:
        return _preview_from_path(file_path, str(material.get("name") or material.get("file_name") or ""))
    return ""


def _has_saved_classification(known: dict[str, Any] | None) -> bool:
    if not isinstance(known, dict):
        return False
    roles = known.get("material_roles")
    return bool(known.get("doc_type")) or (isinstance(roles, list) and len(roles) > 0)


def _enrich_material_roles_with_parsing_tiers(
    material_roles: list[dict[str, Any]],
    *,
    default_parser_type: str = "auto",
) -> list[dict[str, Any]]:
    from data_agent.services.task_classifier import resolve_parsing_tier

    enriched: list[dict[str, Any]] = []
    for item in material_roles:
        role_dict = dict(item)
        file_name = str(role_dict.get("file_name") or role_dict.get("filename") or role_dict.get("name") or "")
        tier = resolve_parsing_tier(
            str(role_dict.get("role") or ""),
            file_name,
            default_parser_type=default_parser_type,
        )
        role_dict["recommended_parsing_tier"] = tier["tier"]
        role_dict["recommended_parser_type"] = tier["parser_type"]
        role_dict["recommended_processing_mode"] = tier["processing_mode"]
        enriched.append(role_dict)
    return enriched


def _preview_processing_mode_for_tier(
    tier: dict[str, Any],
    *,
    fallback: str = "OPTIMAL",
) -> str:
    """Lite tier stays HIGH_SPEED; standard/full use tier processing_mode for MinerU PDF chain."""
    tier_name = str(tier.get("tier") or "standard").strip().lower()
    if tier_name == "lite":
        return "HIGH_SPEED"
    return str(tier.get("processing_mode") or fallback or "OPTIMAL")


_REVIEW_PLUS_SLOT_SPECS: tuple[tuple[str, frozenset[str]], ...] = (
    ("review_rule", frozenset({"review_rule", "checklist"})),
    ("task_book", frozenset({"task_book"})),
    (
        "subject_material",
        frozenset({"subject_report", "subject_document", "supporting_attachment"}),
    ),
)

_REVIEW_PLUS_SLOT_LABELS = {
    "review_rule": "审查规则/检查单",
    "task_book": "研制任务书",
    "subject_material": "被审材料",
}


def compute_review_plus_slot_status(
    material_roles: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """Return Review-Plus slot completeness for wizard routing gates."""
    roles: set[str] = set()
    for item in material_roles or []:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip().lower()
        if role:
            roles.add(role)

    slot_completeness: dict[str, bool] = {}
    missing_slots: list[str] = []
    for slot_id, accepted_roles in _REVIEW_PLUS_SLOT_SPECS:
        present = bool(roles & accepted_roles)
        slot_completeness[slot_id] = present
        if not present:
            missing_slots.append(_REVIEW_PLUS_SLOT_LABELS.get(slot_id, slot_id))

    return {
        "slot_completeness": slot_completeness,
        "missing_slots": missing_slots,
        "review_plus_ready": not missing_slots,
    }


def build_structure_summary(bundle: Any) -> dict[str, Any]:
    """Lightweight structure summary for wizard step 3 confirmation."""
    section_tree = getattr(bundle, "section_tree", None) or {}
    evidence_pool = getattr(bundle, "evidence_pool", None) or {}
    stats = getattr(bundle, "stats", None) or {}
    if isinstance(section_tree, dict):
        sections = section_tree.get("sections") or []
    else:
        sections = getattr(section_tree, "sections", []) or []
    if isinstance(evidence_pool, dict):
        evidences = evidence_pool.get("evidences") or []
    else:
        evidences = getattr(evidence_pool, "evidences", []) or []

    section_count = int(stats.get("section_count") or len(sections))
    evidence_count = int(stats.get("evidence_count") or len(evidences))
    top_sections: list[dict[str, Any]] = []
    for section in sections[:5]:
        if not isinstance(section, dict):
            continue
        title = str(section.get("title") or section.get("heading") or "").strip()
        if not title:
            continue
        top_sections.append(
            {
                "section_id": str(section.get("section_id") or "").strip(),
                "title": title,
                "level": int(section.get("level") or 1),
            }
        )

    from data_agent.parsing.artifact_builder import is_structure_artifact_complete

    parse_artifact = getattr(bundle, "parse_artifact", None) or {}
    document_ir = getattr(bundle, "document_ir", None) or {}
    parse_artifact_for_readiness = parse_artifact if (
        isinstance(parse_artifact, dict)
        and ("section_tree" in parse_artifact or "evidence_pool" in parse_artifact)
    ) else None
    structure_ready = is_structure_artifact_complete(
        section_tree if isinstance(section_tree, dict) else section_tree,
        evidence_pool if isinstance(evidence_pool, dict) else evidence_pool,
        document_ir=document_ir if isinstance(document_ir, dict) else document_ir,
        parse_artifact=parse_artifact_for_readiness,
    )
    return {
        "section_count": section_count,
        "evidence_count": evidence_count,
        "top_sections": top_sections,
        "structure_ready": structure_ready,
    }


def sync_wizard_parse_artifact(run: Any) -> bool:
    """Copy complete wizard parse_preview artifact onto structured_bundle."""
    from data_agent.parsing.artifact_builder import is_parse_artifact_complete

    existing = getattr(run, "structured_bundle", None)
    parse_artifact = dict(getattr(existing, "parse_artifact", None) or {})
    if is_parse_artifact_complete(parse_artifact):
        return True

    preview = getattr(run, "parse_preview", None)
    if not isinstance(preview, dict):
        return False
    parse_artifact = dict(preview.get("parse_artifact") or {})
    if not is_parse_artifact_complete(parse_artifact):
        return False

    existing.parse_artifact = parse_artifact
    existing.document_ir = parse_artifact.get("document_ir") or getattr(existing, "document_ir", None) or {}
    return True


def _build_classification_payload(
    *,
    normalized: list[dict[str, Any]],
    material_roles: list[dict[str, Any]],
    recommended_route: str,
    reason: str,
    confidence: float,
    metadata: dict[str, Any] | None = None,
    doc_type: str | None = None,
    domain: str | None = None,
    classifier: str = "shared_task_classifier",
    default_parser_type: str = "auto",
    slot_status: dict[str, Any] | None = None,
) -> dict[str, Any]:
    slots = slot_status or compute_review_plus_slot_status(material_roles)
    return {
        "doc_type": doc_type or ("批量材料包" if len(normalized) > 1 else "单文档"),
        "domain": domain or "通用审查",
        "recommended_route": recommended_route,
        "reason": reason,
        "confidence": confidence,
        "material_roles": _enrich_material_roles_with_parsing_tiers(
            material_roles,
            default_parser_type=default_parser_type,
        ),
        "metadata": metadata or {},
        "classifier": classifier,
        "slot_completeness": dict(slots.get("slot_completeness") or {}),
        "missing_slots": list(slots.get("missing_slots") or []),
        "review_plus_ready": bool(slots.get("review_plus_ready")),
    }


def _material_raw_bytes(material: SuperAgentMaterial) -> bytes:
    if material.file_path:
        return _safe_super_agent_upload_path(material.file_path).read_bytes()
    if material.content_base64:
        return base64.b64decode(material.content_base64, validate=True)
    return (material.content or "").encode("utf-8")


def _safe_material_filename(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._\-\u4e00-\u9fff]+", "_", name.strip())
    cleaned = cleaned.strip("._")
    return cleaned or "material.txt"


def _ensure_material_source_display_path(
    file_path: str,
    file_name: str,
) -> tuple[str, list[str]]:
    """Ensure a persistent portrait display copy exists beside the uploaded original."""
    from data_agent.parsing.orientation import (
        display_copy_needs_regeneration,
        legacy_normalized_display_paths,
        normalized_display_path_for,
        write_orientation_display_copy,
    )

    source_path = _safe_super_agent_upload_path(file_path)
    normalized_path = normalized_display_path_for(source_path)
    if normalized_path.exists() and not display_copy_needs_regeneration(source_path, normalized_path):
        try:
            relative = str(normalized_path.resolve().relative_to(SUPER_AGENT_UPLOAD_DIR.resolve()))
        except ValueError:
            return "", []
        return relative.replace("\\", "/"), []

    for legacy_path in legacy_normalized_display_paths(source_path):
        if legacy_path.exists() and legacy_path != normalized_path:
            try:
                legacy_path.unlink()
            except OSError:
                logger.warning("[SuperAgent] failed to remove legacy normalized display file: %s", legacy_path)

    changed, warnings = write_orientation_display_copy(
        str(source_path),
        file_name,
        str(normalized_path),
    )
    if not changed:
        return "", list(warnings)
    try:
        relative = str(normalized_path.resolve().relative_to(SUPER_AGENT_UPLOAD_DIR.resolve()))
    except ValueError:
        return "", list(warnings)
    return relative.replace("\\", "/"), list(warnings)


def _persist_upload_material(
    run_id: str,
    material: SuperAgentMaterial,
    *,
    index: int,
) -> tuple[dict[str, Any], list[str]]:
    """Prepare upload material for parsers while preserving text for GNC prompts."""
    warnings: list[str] = []
    prepared = material.model_dump()
    if material.file_path:
        path = _safe_super_agent_upload_path(material.file_path)
        prepared["file_path"] = str(path)
        display_path, orientation_warnings = _ensure_material_source_display_path(
            material.file_path,
            material.name or path.name,
        )
        if display_path:
            prepared["source_display_path"] = display_path
        warnings.extend(orientation_warnings)
        if not prepared.get("content"):
            try:
                prepared["content"] = path.read_text(encoding="utf-8", errors="ignore")
            except UnicodeDecodeError:
                prepared["content"] = ""
        prepared["content_base64"] = ""
        return prepared, warnings

    try:
        raw_content = _material_raw_bytes(material)
    except Exception as exc:
        raise ValueError(f"材料读取失败 {material.name or index}: {exc}") from exc
    if not raw_content:
        warnings.append(f"材料为空: {material.name or index}")
        return prepared, warnings

    upload_dir = SUPER_AGENT_UPLOAD_DIR / "super_agent" / run_id
    upload_dir.mkdir(parents=True, exist_ok=True)
    filename = _safe_material_filename(material.name or f"material-{index}.txt")
    path = upload_dir / f"{index:03d}-{filename}"
    path.write_bytes(raw_content)
    prepared["file_path"] = str(path)
    prepared["content_base64"] = ""
    if not prepared.get("content"):
        try:
            prepared["content"] = raw_content.decode("utf-8")
        except UnicodeDecodeError:
            prepared["content"] = material.content_preview or ""
    return prepared, warnings


def enrich_material_previews(materials: list[SuperAgentMaterial]) -> list[SuperAgentMaterial]:
    enriched: list[SuperAgentMaterial] = []
    for material in materials:
        preview = (material.content_preview or "").strip() or _material_preview_text(material)
        enriched.append(material.model_copy(update={"content_preview": preview}))
    return enriched


def _safe_super_agent_upload_path(file_path: str) -> Path:
    raw = file_path.strip()
    if not raw:
        raise ValueError("上传材料 file_path 为空")
    path = Path(raw)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("上传材料 file_path 不允许使用绝对路径或路径遍历")
    root = SUPER_AGENT_UPLOAD_DIR.resolve()
    resolved = (root / path).resolve()
    if root != resolved and root not in resolved.parents:
        raise ValueError("上传材料 file_path 超出 SUPER_AGENT_UPLOAD_DIR")
    if not resolved.exists() or not resolved.is_file():
        raise ValueError(f"上传材料不存在: {file_path}")
    return resolved
