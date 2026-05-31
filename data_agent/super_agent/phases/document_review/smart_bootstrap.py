"""SMART synthetic review context when task book / checklist slots are missing."""

from __future__ import annotations

import re
from typing import Any

_METRIC_PATTERN = re.compile(
    r"(\d+(?:\.\d+)?\s*(?:deg|°|rad|m/s|N·m|Nm|Hz|kHz|MHz|W|V|A|kg|g|ms|s|min|h|%|℃|°C))"
    r"|(?:指标|约束|阈值|容差|精度|范围|上限|下限)",
    re.IGNORECASE,
)


def _sections_from_run(run: Any) -> list[dict[str, Any]]:
    bundle = getattr(run, "structured_bundle", None)
    parse_artifact: dict[str, Any] = {}
    if bundle is not None:
        parse_artifact = dict(getattr(bundle, "parse_artifact", None) or {})
        section_tree = parse_artifact.get("section_tree") or getattr(bundle, "section_tree", None) or {}
    else:
        section_tree = {}
    if not section_tree and isinstance(getattr(run, "parse_preview", None), dict):
        preview = run.parse_preview or {}
        parse_artifact = dict(preview.get("parse_artifact") or {})
        section_tree = parse_artifact.get("section_tree") or {}
    if isinstance(section_tree, dict):
        return [item for item in section_tree.get("sections") or [] if isinstance(item, dict)]
    return []


def _evidences_from_run(run: Any) -> list[dict[str, Any]]:
    bundle = getattr(run, "structured_bundle", None)
    evidence_pool: dict[str, Any] = {}
    if bundle is not None:
        parse_artifact = dict(getattr(bundle, "parse_artifact", None) or {})
        evidence_pool = parse_artifact.get("evidence_pool") or getattr(bundle, "evidence_pool", None) or {}
    if not evidence_pool and isinstance(getattr(run, "parse_preview", None), dict):
        preview = run.parse_preview or {}
        parse_artifact = dict(preview.get("parse_artifact") or {})
        evidence_pool = parse_artifact.get("evidence_pool") or {}
    if isinstance(evidence_pool, dict):
        return [item for item in evidence_pool.get("evidences") or [] if isinstance(item, dict)]
    return []


def _parsed_doc_titles(run: Any) -> list[str]:
    bundle = getattr(run, "structured_bundle", None)
    parse_artifact: dict[str, Any] = {}
    if bundle is not None:
        parse_artifact = dict(getattr(bundle, "parse_artifact", None) or {})
    if not parse_artifact and isinstance(getattr(run, "parse_preview", None), dict):
        parse_artifact = dict((run.parse_preview or {}).get("parse_artifact") or {})
    titles: list[str] = []
    for item in parse_artifact.get("parsed_documents") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("file_name") or item.get("name") or "").strip()
        if name:
            titles.append(name)
    return titles


def _evidence_excerpt(evidence: dict[str, Any]) -> str:
    for key in ("excerpt", "quote", "text", "content"):
        value = str(evidence.get(key) or "").strip()
        if value:
            return value[:400]
    return ""


def _attach_evidence_to_check_items(
    check_items: list[dict[str, Any]],
    evidences: list[dict[str, Any]],
    sections: list[dict[str, Any]],
) -> None:
    for index, item in enumerate(check_items):
        if item.get("source_quote") and item.get("source_evidence_ref"):
            continue
        if evidences:
            evidence = evidences[index % len(evidences)]
            excerpt = _evidence_excerpt(evidence)
            if excerpt:
                item.setdefault("source_evidence_ref", str(evidence.get("evidence_id") or evidence.get("id") or ""))
                item.setdefault("source_quote", excerpt[:240])
                item.setdefault("source", item.get("source") or "evidence_pool")
                continue
        if sections:
            section = sections[index % len(sections)]
            text = str(section.get("text") or section.get("content") or section.get("title") or "").strip()
            if text:
                item.setdefault("source_evidence_ref", str(section.get("section_id") or section.get("id") or ""))
                item.setdefault("source_quote", text[:240])
                item.setdefault("source", item.get("source") or "section_tree")


def _synthetic_evidence_refs_from_sections(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for section in sections[:20]:
        section_id = str(section.get("section_id") or section.get("id") or "").strip()
        if not section_id:
            continue
        refs.append(
            {
                "evidence_id": section_id,
                "page": section.get("page") or section.get("page_no"),
                "source_file_name": str(section.get("source_file_name") or ""),
                "excerpt": str(section.get("text") or section.get("content") or section.get("title") or "")[:400],
            }
        )
    return refs


def build_bootstrap_summary(payload: dict[str, Any]) -> dict[str, Any]:
    check_items = payload.get("synthetic_check_items") or []
    evidence_refs = payload.get("source_evidence_refs") or []
    bootstrap_mode = str(payload.get("bootstrap_mode") or "")
    return {
        "bootstrap_mode": bootstrap_mode,
        "synthetic_check_item_count": len(check_items),
        "source_evidence_ref_count": len(evidence_refs),
        "synthetic_context_label": (
            "已使用智能合成审查上下文" if bootstrap_mode == "smart_synthetic_context" else ""
        ),
    }


def _metric_check_items(evidences: list[dict[str, Any]], sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add_from_text(text: str, *, source: str, ref: str) -> None:
        if not text or len(items) >= 10:
            return
        for match in _METRIC_PATTERN.finditer(text):
            snippet = match.group(0).strip()
            if len(snippet) < 2 or snippet in seen:
                continue
            seen.add(snippet)
            items.append(
                {
                    "check_item_id": f"SYN-MET-{len(items) + 1:03d}",
                    "title": f"技术指标/约束复核：{snippet[:48]}",
                    "requirement_text": f"确认文档中「{snippet}」类指标/约束在方案与结论中一致且可审计。",
                    "source": source,
                    "source_evidence_ref": ref,
                }
            )
            if len(items) >= 10:
                return

    for evidence in evidences:
        excerpt = _evidence_excerpt(evidence)
        ref = str(evidence.get("evidence_id") or evidence.get("id") or "")
        add_from_text(excerpt, source="evidence_pool", ref=ref)

    for section in sections:
        text = str(section.get("text") or section.get("content") or section.get("title") or "")
        ref = str(section.get("section_id") or section.get("id") or "")
        add_from_text(text, source="section_tree", ref=ref)

    return items


def synthesize_minimal_review_context(run: Any, objective: str) -> dict[str, Any]:
    """Build minimal checklist/task-book context without external models."""
    objective_text = str(objective or getattr(run, "objective", "") or "").strip()
    sections = _sections_from_run(run)
    evidences = _evidences_from_run(run)
    doc_titles = _parsed_doc_titles(run)

    source_evidence_refs: list[dict[str, Any]] = []
    for evidence in evidences[:20]:
        ref_id = str(evidence.get("evidence_id") or evidence.get("id") or "").strip()
        if not ref_id:
            continue
        source_evidence_refs.append(
            {
                "evidence_id": ref_id,
                "page": evidence.get("page") or evidence.get("page_no"),
                "source_file_name": str(evidence.get("source_file_name") or ""),
                "excerpt": _evidence_excerpt(evidence),
            }
        )

    synthetic_check_items: list[dict[str, Any]] = []

    if objective_text:
        synthetic_check_items.append(
            {
                "check_item_id": "SYN-OBJ-001",
                "title": "审查目标覆盖",
                "requirement_text": f"围绕用户审查目标「{objective_text}」核对文档是否给出可审计的结论与依据。",
                "source": "objective",
            }
        )
        synthetic_check_items.append(
            {
                "check_item_id": "SYN-OBJ-002",
                "title": "目标—证据可追溯",
                "requirement_text": f"检查与「{objective_text}」相关的论述是否能在正文章节或证据池中找到对应引用。",
                "source": "objective",
            }
        )

    section_count = len(sections)
    evidence_count = len(evidences)
    doc_label = "、".join(doc_titles[:3]) if doc_titles else "当前送审文档"
    synthetic_check_items.append(
        {
            "check_item_id": "SYN-DOC-001",
            "title": "文档结构与完整性",
            "requirement_text": (
                f"确认 {doc_label} 具备可定位章节（已识别 {section_count} 个章节）"
                f"与证据条目（{evidence_count} 条），版本/目录信息无重大缺失。"
            ),
            "source": "structure",
        }
    )
    synthetic_check_items.append(
        {
            "check_item_id": "SYN-DOC-002",
            "title": "跨章节一致性",
            "requirement_text": "核对摘要、指标、结论与正文/表格中的数值、单位、术语是否前后一致。",
            "source": "structure",
        }
    )

    synthetic_check_items.extend(_metric_check_items(evidences, sections))

    if len(synthetic_check_items) < 3:
        synthetic_check_items.append(
            {
                "check_item_id": "SYN-GEN-001",
                "title": "通用合规性预审",
                "requirement_text": "对单文档智能审查场景应执行可解释的结构化预审，并标注需人工复核的不确定项。",
                "source": "bootstrap",
            }
        )

    synthetic_check_items = synthetic_check_items[:10]
    _attach_evidence_to_check_items(synthetic_check_items, evidences, sections)

    if not source_evidence_refs and sections:
        source_evidence_refs = _synthetic_evidence_refs_from_sections(sections)

    requirement_lines = [
        f"1. 审查目标应覆盖：{objective_text or '文档核心结论'}。",
        "2. 文档指标与验收要求应可追溯到章节或证据池。",
        "3. 跨章节术语、数值与表格数据应保持一致。",
    ]
    for item in synthetic_check_items[:5]:
        requirement_text = str(item.get("requirement_text") or "").strip()
        if len(requirement_text) >= 6:
            requirement_lines.append(f"- {requirement_text}")

    synthetic_task_book = (
        "【SMART 合成任务上下文】本轮未提供完整 Review-Plus 任务书/检查单槽位，"
        "系统已基于用户审查目标、结构化章节与证据池自动生成最小审查上下文，"
        f"供专家 Harness 与确定性预审使用。审查目标：{objective_text or '（未指定）'}。\n"
        + "\n".join(requirement_lines)
    )

    payload = {
        "synthetic_check_items": synthetic_check_items,
        "synthetic_task_book": synthetic_task_book,
        "bootstrap_mode": "smart_synthetic_context",
        "source_evidence_refs": source_evidence_refs,
        "objective": objective_text,
    }
    payload["bootstrap_summary"] = build_bootstrap_summary(payload)
    return payload


__all__ = ["build_bootstrap_summary", "synthesize_minimal_review_context"]
