"""Evidence mapping helpers for Review-Plus.

Review-Plus treats keyword matching as an auxiliary signal only. The primary
review context should come from Document IR (layout/table/visual elements) and
structured evidence_pool / section_tree, then be narrowed by lightweight lexical
scoring and LLM evidence selection.
"""

from __future__ import annotations

import re
from typing import Any

from data_agent.review_plus.schemas import (
    ReviewPlusMaterialRole,
    ReviewPlusSectionMapping,
)
from data_agent.review_plus.section_text_utils import get_mapped_section_texts
from data_agent.review_plus.text_utils import (
    dict_items,
    iter_material_lines,
    role_value,
    tokens,
)
from data_agent.parsing.document_ir_consumer import iter_ir_evidence_candidates


def _material_role_by_name(task: Any) -> dict[str, str]:
    roles: dict[str, str] = {}
    for material in getattr(task, "materials", []) or []:
        roles[getattr(material, "name", "")] = role_value(material)
    return roles


def _is_review_subject_role(role: str) -> bool:
    return role not in {
        ReviewPlusMaterialRole.REVIEW_RULE.value,
        ReviewPlusMaterialRole.CHECKLIST.value,
    }


def _collect_structured_evidence(task: Any) -> list[dict[str, Any]]:
    """Collect candidates from evidence_pool, section_tree and parsed chunks."""
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    roles_by_name = _material_role_by_name(task)

    def add_candidate(
        *,
        evidence_id: str,
        material_name: str,
        section_id: str,
        section_title: str,
        text: str,
        source_kind: str,
        summary: str = "",
    ) -> None:
        clean_text = (text or summary or "").strip()
        if len(clean_text) < 8:
            return
        role = roles_by_name.get(material_name, "")
        if material_name and not _is_review_subject_role(role):
            return
        key = evidence_id or f"{material_name}:{section_id}:{source_kind}:{len(candidates)}"
        if key in seen:
            return
        seen.add(key)
        candidates.append({
            "evidence_id": key,
            "material_name": material_name,
            "section_id": section_id or key,
            "section_title": section_title or material_name or "结构化文档块",
            "text": clean_text,
            "summary": summary,
            "tokens": tokens(" ".join([section_title or "", summary or "", clean_text])),
            "source_kind": source_kind,
        })

    section_titles: dict[str, str] = {}
    section_files: dict[str, str] = {}
    for section in dict_items(getattr(task, "section_tree", {}), "sections"):
        section_id = str(section.get("section_id") or "")
        section_title = str(section.get("title") or "")
        source_file = str(section.get("source_file_name") or "")
        if section_id:
            section_titles[section_id] = section_title
            section_files[section_id] = source_file
        add_candidate(
            evidence_id=f"sec:{section_id}" if section_id else "",
            material_name=source_file,
            section_id=section_id,
            section_title=section_title,
            text=str(section.get("text") or ""),
            source_kind="section",
        )

    for evidence in dict_items(getattr(task, "evidence_pool", {}), "evidences"):
        section_id = str(evidence.get("section_id") or "")
        material_name = str(evidence.get("source_file_name") or section_files.get(section_id, ""))
        text = str(evidence.get("excerpt") or evidence.get("summary") or "")
        add_candidate(
            evidence_id=str(evidence.get("evidence_id") or f"ev:{section_id}:{len(candidates)}"),
            material_name=material_name,
            section_id=section_id,
            section_title=section_titles.get(section_id, ""),
            text=text,
            summary=str(evidence.get("summary") or ""),
            source_kind=str(evidence.get("source_type") or "evidence_pool"),
        )

    document_ir = getattr(task, "document_ir", {}) or {}
    if isinstance(document_ir, dict):
        for ir_candidate in iter_ir_evidence_candidates(document_ir):
            add_candidate(
                evidence_id=ir_candidate["evidence_id"],
                material_name=ir_candidate["material_name"],
                section_id=ir_candidate["section_id"],
                section_title=ir_candidate["section_title"],
                text=ir_candidate["text"],
                summary=ir_candidate.get("summary", ""),
                source_kind=ir_candidate["source_kind"],
            )

    for chunk in getattr(task, "parsed_documents", []) or []:
        if not isinstance(chunk, dict):
            continue
        material_name = str(chunk.get("source_file_name") or chunk.get("document_name") or "")
        section_id = str(chunk.get("section_id") or chunk.get("chunk_id") or "")
        add_candidate(
            evidence_id=str(chunk.get("chunk_id") or f"chunk:{section_id}:{len(candidates)}"),
            material_name=material_name,
            section_id=section_id,
            section_title=str(chunk.get("section_title") or chunk.get("title") or ""),
            text=str(chunk.get("chunk_text") or chunk.get("text") or ""),
            source_kind="chunk",
        )

    return candidates


def _score_evidence_candidate(item_tokens: set[str], evidence: dict[str, Any]) -> float:
    evidence_tokens = evidence.get("tokens") or set()
    if not item_tokens or not evidence_tokens:
        return 0.0
    overlap = item_tokens & evidence_tokens
    if not overlap:
        return 0.0
    containment = len(overlap) / max(len(item_tokens), 1)
    density = len(overlap) / max(len(evidence_tokens), 1)
    source_kind = str(evidence.get("source_kind") or "")
    source_boost = 0.03 if source_kind != "material_line" else 0.0
    if source_kind in {"document_ir_visual", "parse_calibration", "visual_description"}:
        source_boost += 0.05
    return min(1.0, 0.75 * containment + 0.25 * density + source_boost)


def _candidate_source_label(candidates: list[dict[str, Any]]) -> str:
    kinds = {str(item.get("source_kind") or "") for item in candidates}
    if not candidates:
        return "none"
    if kinds <= {"material_line"}:
        return "line_fallback"
    if "material_line" in kinds:
        return "structured_plus_line"
    return "structured"


def map_check_items_to_evidence(task: Any, *, max_evidence_per_item: int = 8) -> list[ReviewPlusSectionMapping]:
    structured_candidates = _collect_structured_evidence(task)
    fallback_lines = iter_material_lines(task, min_line_length=8)
    evidence_candidates = structured_candidates or fallback_lines
    mappings: list[ReviewPlusSectionMapping] = []
    for item in getattr(task, "check_items", []) or []:
        item_text = " ".join([
            item.title or "",
            item.requirement_text or "",
            item.acceptance_criteria or "",
            item.applicable_scope or "",
        ])
        item_tokens = tokens(item_text)
        scored: list[tuple[float, dict[str, Any]]] = []
        for evidence in evidence_candidates:
            score = _score_evidence_candidate(item_tokens, evidence)
            if score > 0:
                scored.append((score, evidence))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        top = scored[:max_evidence_per_item]

        if not top and structured_candidates:
            top = [(0.01, evidence) for evidence in structured_candidates[:max_evidence_per_item]]
        elif not top and fallback_lines:
            top = [(0.01, evidence) for evidence in fallback_lines[:max_evidence_per_item]]

        source_label = _candidate_source_label([entry for _, entry in top])
        method = "structured_keyword_evidence" if source_label.startswith("structured") else "line_keyword_evidence"
        if top and top[0][0] <= 0.01:
            method = "structured_broad_candidates" if source_label.startswith("structured") else "line_broad_candidates"

        mappings.append(ReviewPlusSectionMapping(
            check_item_id=item.check_item_id,
            section_ids=[entry["section_id"] for _, entry in top],
            section_titles=[entry["section_title"] for _, entry in top],
            evidence_ids=[entry["evidence_id"] for _, entry in top],
            evidence_quotes=[entry["text"] for _, entry in top],
            confidence=round(top[0][0], 4) if top else 0.0,
            method=method,
            rationale=(
                "结构化文档块候选，关键词仅用于辅助排序，后续由 LLM 进行证据选择/符合性判断"
                if top and source_label.startswith("structured")
                else "原文行级候选兜底，关键词仅用于辅助排序"
                if top
                else "未找到可供 LLM 审查的文档证据候选"
            ),
        ))
    return mappings


_TASK_BOOK_ROLES = {ReviewPlusMaterialRole.TASK_BOOK.value}
_SUBJECT_ROLES = {
    ReviewPlusMaterialRole.SUBJECT_REPORT.value,
    ReviewPlusMaterialRole.SUBJECT_DOCUMENT.value,
    ReviewPlusMaterialRole.SUPPORTING_ATTACHMENT.value,
}


def section_mapping_refs_by_role(
    task: Any,
    check_item_id: str,
) -> tuple[list[str], list[str]]:
    """Split precomputed section_mappings evidence IDs by material role."""
    roles_by_name = _material_role_by_name(task)
    mapping_by_id = {
        mapping.check_item_id: mapping
        for mapping in getattr(task, "section_mappings", []) or []
    }
    mapping = mapping_by_id.get(check_item_id)
    if not mapping:
        return [], []

    task_refs: list[str] = []
    subject_refs: list[str] = []
    for evidence_id, quote in zip(mapping.evidence_ids, mapping.evidence_quotes):
        material_name = ""
        if ":" in evidence_id:
            parts = evidence_id.split(":")
            if len(parts) >= 2:
                material_name = parts[1]
        role = roles_by_name.get(material_name, "")
        if role in _TASK_BOOK_ROLES:
            task_refs.append(evidence_id)
        elif role in _SUBJECT_ROLES or not role:
            subject_refs.append(evidence_id)
        elif quote:
            subject_refs.append(evidence_id)
    return task_refs, subject_refs


def build_semantic_cross_document_items(task: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    evidence_lines = iter_material_lines(task, min_line_length=8)
    report_lines = [
        item for item in evidence_lines
        if _material_role_by_name(task).get(item["material_name"], "") in {
            ReviewPlusMaterialRole.SUBJECT_REPORT.value,
            ReviewPlusMaterialRole.SUBJECT_DOCUMENT.value,
        }
    ]
    task_lines = [
        item for item in evidence_lines
        if _material_role_by_name(task).get(item["material_name"], "") == ReviewPlusMaterialRole.TASK_BOOK.value
    ]

    def add(item_type: str, severity: str, title: str, description: str, quotes: list[str]) -> None:
        items.append({
            "review_item_id": f"rp-semantic-{item_type}-{len(items) + 1}",
            "item_type": item_type,
            "severity": severity,
            "title": title,
            "description": description,
            "impact": "多份文档之间缺少可印证关系会降低审查结论可信度。",
            "recommendation": "补充明确引用、章节对应关系或修订说明。",
            "source_artifact_ids": [],
            "target_artifact_ids": [],
            "evidence_ids": [],
            "source_quote": "\n".join(quotes[:3]),
            "status": "open",
        })

    for line in task_lines[:30]:
        if not re.search(r"要求|应|交付|验收|指标|可靠性|安全性", line["text"]):
            continue
        best = 0.0
        for report in report_lines:
            overlap = line["tokens"] & report["tokens"]
            best = max(best, len(overlap) / max(len(line["tokens"]), 1))
        if best < 0.08:
            add(
                "task_book_requirement_gap",
                "major",
                "任务书要求未在报告中找到明确印证",
                f"任务书条目未在被审报告中找到足够直接的对应证据: {line['text'][:120]}",
                [line["text"]],
            )

    return items


__all__ = [
    "map_check_items_to_evidence",
    "section_mapping_refs_by_role",
    "build_semantic_cross_document_items",
    "get_mapped_section_texts",
]
