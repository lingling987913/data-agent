"""GNC design-review workflow adapted from aqua for data-agent."""

from __future__ import annotations

import json
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

try:
    from agno.workflow import Step, StepInput, StepOutput, Workflow
except ModuleNotFoundError:  # pragma: no cover - import compatibility for minimal test envs
    @dataclass
    class StepInput:  # type: ignore[no-redef]
        input: Any = None
        previous_step_content: str | None = None

    @dataclass
    class StepOutput:  # type: ignore[no-redef]
        content: Any = None

    @dataclass
    class Step:  # type: ignore[no-redef]
        name: str
        executor: Any
        description: str = ""

    @dataclass
    class Workflow:  # type: ignore[no-redef]
        id: str
        name: str
        description: str
        steps: list[Step]
from pydantic import BaseModel, ValidationError

from data_agent.core.config import SUPER_AGENT_UPLOAD_DIR
from data_agent.integrations.satellite_review.gnc_agents import (
    COMMITTEE_AGENT_BUILDERS,
    gnc_chief_reviewer,
    review_editor,
)
from data_agent.integrations.satellite_review.gnc_schemas import (
    GNCChiefDecisionOutput,
    GNCCommitteeOutput,
    GNCConflictReport,
    GNCEditorialOutput,
    GNCExpertFinding,
    GNCReviewMode,
    GNCReviewRequest,
    GNCReviewResult,
    GNCReviewStatus,
)
from data_agent.integrations.satellite_review.arbitration_service import (
    annotate_rid_prior_cycle_status,
    apply_chief_arbitration,
    build_editorial_minutes_struct,
    build_rule_rid_candidates,
    build_trace_context,
    detect_expert_opinion_conflicts,
    merge_editorial_rid_items,
    summarize_review_risk_categories,
    summarize_unit_results,
)
from data_agent.integrations.satellite_review.review_units import (
    build_unit_evidence_bundles_for_workflow,
    build_unit_template_gatekeeping,
    run_unit_review,
    select_units_by_signals,
)
from data_agent.review_workbench.issue_taxonomy import resolve_verdict_label_zh

logger = logging.getLogger(__name__)

_TEXT_EXTENSIONS = {".md", ".markdown", ".txt", ".csv", ".json", ".yaml", ".yml"}
_SEVERITY_RANK = {"info": 0, "suggestion": 1, "minor": 2, "major": 3, "critical": 4}
_JUDGMENT_WORDS = {
    "满足": "satisfied",
    "通过": "satisfied",
    "不满足": "not_satisfied",
    "不足": "insufficient_evidence",
    "缺失": "insufficient_evidence",
    "矛盾": "not_satisfied",
}


def _now() -> str:
    return datetime.now().isoformat()


def _as_json(data: dict[str, Any]) -> StepOutput:
    return StepOutput(content=json.dumps(data, ensure_ascii=False, default=str))


def _load_json(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"GNC workflow received non-JSON step content: {exc}") from exc


def _response_as_model(response: Any, schema: type[BaseModel]) -> BaseModel:
    from data_agent.agno_structured import validate_structured_output

    payload = getattr(response, "content", response)
    return validate_structured_output(payload, schema)


def _run_structured_agent(agent: Any, prompt: str, schema: type[BaseModel]) -> BaseModel:
    from data_agent.agno_structured import run_agent_with_validation

    return run_agent_with_validation(agent, prompt, schema)


def _fallback_editorial_from_committee(committee: dict[str, Any], *, reason: str) -> dict[str, Any]:
    """Degrade editorial synthesis when structured LLM output is empty or invalid."""
    findings = [item for item in (committee.get("findings") or []) if isinstance(item, dict)]
    rule_rid_candidates = build_rule_rid_candidates(committee, findings)
    llm_like_items = [
        {
            "discipline": finding.get("discipline", ""),
            "severity": finding.get("severity", "major"),
            "description": finding.get("description", finding.get("title", "")),
            "basis": f"来源 finding: {finding.get('finding_id', '')}",
            "related_finding_ids": [finding.get("finding_id", "")],
            "source_type": "finding_merged",
        }
        for finding in findings[:50]
        if finding.get("severity") not in ("suggestion", "info")
    ]
    # Rule-derived RIDs are merged once in editorial_synthesis_step; avoid double merge here.
    rid_items = llm_like_items
    preview_lines = [
        f"- [{finding.get('severity', '')}] {finding.get('title', '')}: {finding.get('description', '')}"
        for finding in findings[:30]
        if finding.get("title") or finding.get("description")
    ]
    rule_rid_lines = [
        f"- [{candidate.get('severity', '')}] {candidate.get('description', '')}"
        for candidate in rule_rid_candidates[:20]
        if candidate.get("description")
    ]
    minutes = (
        f"合稿步骤 LLM 结构化输出失败（{reason}），已降级展示 committee findings 与规则判定 RID 候选。"
        + (f"\n\n专家问题摘要：\n" + "\n".join(preview_lines) if preview_lines else "\n\n本轮 committee 未产出 findings。")
        + (f"\n\n规则判定 RID 候选：\n" + "\n".join(rule_rid_lines) if rule_rid_lines else "")
    )
    return {
        "rid_items": rid_items,
        "minutes": minutes,
        "conclusion_draft": (
            f"共识别 {len(findings)} 条专家审查意见、{len(rid_items)} 条 finding 归并项"
            f"（另有 {len(rule_rid_candidates)} 条规则判定候选待归并）；合稿/总师 LLM 步骤未完成，请人工复核。"
            if findings or rid_items or rule_rid_candidates
            else "合稿步骤未完成且 committee 未产出 findings，请检查材料正文与 LLM 配置后重试。"
        ),
        "residual_risks": [
            str(conflict.get("summary", ""))
            for conflict in (committee.get("conflicts") or [])
            if isinstance(conflict, dict) and conflict.get("summary")
        ][:10],
        "rule_rid_candidate_count": len(rule_rid_candidates),
        "degraded": True,
        "degrade_reason": reason,
    }


def _fallback_chief_from_committee(
    committee: dict[str, Any],
    editorial: dict[str, Any],
    *,
    reason: str,
) -> dict[str, Any]:
    findings = [item for item in (committee.get("findings") or []) if isinstance(item, dict)]
    unit_results = committee.get("unit_results") or []
    expert_conflicts = detect_expert_opinion_conflicts(unit_results)
    risk_summary = summarize_review_risk_categories(unit_results)
    requires_arbitration = bool(committee.get("failures")) or any(
        item.get("requires_arbitration") for item in expert_conflicts
    )
    key_risks = [
        str(conflict.get("summary", ""))
        for conflict in expert_conflicts
        if conflict.get("summary")
    ][:8]
    if risk_summary["missing_claim_count"]:
        key_risks.append(f"缺项类问题 {risk_summary['missing_claim_count']} 条")
    if risk_summary["rule_inconsistent_count"]:
        key_risks.append(f"规则不一致问题 {risk_summary['rule_inconsistent_count']} 条")
    if not key_risks and findings:
        key_risks = [
            compact
            for compact in (
                f"{finding.get('title', '')}: {finding.get('description', '')}"[:160]
                for finding in findings[:5]
            )
            if compact.strip(": ")
        ]
    verdict = "conditionally_approved" if findings and not requires_arbitration else "needs_review"
    decision = {
        "verdict": verdict,
        "rationale": (
            f"总师审定步骤 LLM 结构化输出失败（{reason}），已基于 {len(findings)} 条 committee findings 降级输出。"
            + (f" 合稿结论草案：{editorial.get('conclusion_draft', '')}"[:500])
        ),
        "key_risks": key_risks,
        "conflict_resolutions": [],
        "requires_arbitration": requires_arbitration,
        "arbitration_items": [],
        "degraded": True,
        "degrade_reason": reason,
    }
    return apply_chief_arbitration(
        decision,
        expert_conflicts=expert_conflicts,
        committee_conflicts=committee.get("conflicts") or [],
        failures=committee.get("failures") or {},
    )


def _is_recoverable_structured_error(exc: BaseException) -> bool:
    return isinstance(exc, (ValidationError, ValueError, json.JSONDecodeError)) or (
        type(exc).__name__ == "SchemaValidationError"
    )


def _run_structured_agent_or_fallback(
    agent: Any,
    prompt: str,
    schema: type[BaseModel],
    *,
    fallback: Callable[[str], dict[str, Any]] | None = None,
) -> BaseModel:
    try:
        return _run_structured_agent(agent, prompt, schema)
    except Exception as exc:
        if fallback is None or not _is_recoverable_structured_error(exc):
            raise
        logger.warning(
            "gnc_structured_agent_degraded schema=%s error=%s",
            getattr(schema, "__name__", str(schema)),
            exc,
        )
        payload = fallback(str(exc))
        return schema.model_validate(payload)


def _safe_gnc_file_path(file_path: str) -> Path:
    raw = file_path.strip()
    if not raw:
        raise ValueError("GNC document file_path is empty")
    path = Path(raw)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("GNC document file_path must be relative and must not contain path traversal")
    root = SUPER_AGENT_UPLOAD_DIR.resolve()
    resolved = (root / path).resolve()
    if root != resolved and root not in resolved.parents:
        raise ValueError("GNC document file_path is outside SUPER_AGENT_UPLOAD_DIR")
    return resolved


def _content_from_document_ir(document_ir: dict[str, Any], *, doc_name: str = "") -> str:
    parts: list[str] = []
    for block in document_ir.get("layout_blocks") or []:
        if not isinstance(block, dict):
            continue
        source_name = str(block.get("source_file_name") or "")
        if doc_name and source_name and source_name != doc_name:
            continue
        text = str(block.get("text") or "").strip()
        if text:
            parts.append(text)
    return "\n\n".join(parts)


def _document_ir_for_read(doc: dict[str, Any], metadata: dict[str, Any] | None = None) -> dict[str, Any] | None:
    raw_ir = doc.get("document_ir")
    if isinstance(raw_ir, dict) and raw_ir.get("layout_blocks"):
        return raw_ir
    if not metadata:
        return None
    bundle = metadata.get("structured_bundle") or {}
    if not isinstance(bundle, dict):
        return None
    bundle_ir = bundle.get("document_ir")
    if isinstance(bundle_ir, dict) and bundle_ir.get("layout_blocks"):
        return bundle_ir
    return None


def _read_document_content(doc: dict[str, Any], *, metadata: dict[str, Any] | None = None) -> str:
    doc_name = str(doc.get("name") or Path(str(doc.get("file_path") or "")).name or "")
    document_ir = _document_ir_for_read(doc, metadata)
    if document_ir:
        content = _content_from_document_ir(document_ir, doc_name=doc_name)
        if content.strip():
            return content

    content = str(doc.get("content") or "")
    file_path = str(doc.get("file_path") or "")
    if content or not file_path:
        return content
    try:
        path = _safe_gnc_file_path(file_path)
    except ValueError:
        return content
    if not path.exists() or path.suffix.lower() not in _TEXT_EXTENSIONS:
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


def _make_evidence_id(index: int) -> str:
    return f"EVD-{index:04d}"


def _clip(value: str, limit: int = 900) -> str:
    value = value.strip()
    return value if len(value) <= limit else value[:limit] + "..."


def _infer_judgment(text: str, fallback: str = "insufficient_evidence") -> str:
    for key, judgment in _JUDGMENT_WORDS.items():
        if key in text:
            return judgment
    return fallback


def _struct_from_existing_bundle(intake: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]] | None:
    """Reuse Super Agent parsed section/evidence IR when available."""
    bundle = intake.get("metadata", {}).get("structured_bundle") or {}
    if not isinstance(bundle, dict):
        return None
    raw_tree = bundle.get("section_tree") or {}
    raw_pool = bundle.get("evidence_pool") or {}
    sections = raw_tree.get("sections") if isinstance(raw_tree, dict) else []
    evidences = raw_pool.get("evidences") if isinstance(raw_pool, dict) else []
    if not isinstance(sections, list) or not isinstance(evidences, list) or not evidences:
        return None

    section_by_id = {
        str(section.get("section_id") or ""): section
        for section in sections
        if isinstance(section, dict) and section.get("section_id")
    }
    gnc_evidences: list[dict[str, Any]] = []
    grouped_sections: dict[str, list[dict[str, Any]]] = {}
    for index, evidence in enumerate(evidences, start=1):
        if not isinstance(evidence, dict):
            continue
        evidence_id = str(evidence.get("evidence_id") or _make_evidence_id(index))
        section_id = str(evidence.get("section_id") or "")
        section = section_by_id.get(section_id, {})
        document_name = str(
            evidence.get("source_file_name")
            or section.get("source_file_name")
            or evidence.get("document_name")
            or ""
        )
        title = str(section.get("title") or evidence.get("title") or section_id or document_name)
        quote = _clip(
            str(
                evidence.get("excerpt")
                or evidence.get("summary")
                or section.get("text")
                or ""
            ),
            1200,
        )
        grouped_sections.setdefault(document_name or "document", []).append(
            {"section_id": section_id, "title": title, "evidence_id": evidence_id}
        )
        gnc_evidences.append(
            {
                "evidence_id": evidence_id,
                "document_name": document_name,
                "section_id": section_id,
                "title": title,
                "quote": quote,
                "source_type": evidence.get("source_type") or "uploaded_document",
                "block_ids": list(evidence.get("block_ids") or []),
                "matched_keywords": list(evidence.get("matched_keywords") or []),
            }
        )
    if not gnc_evidences:
        return None
    return {
        "documents": [
            {"name": document_name, "sections": doc_sections}
            for document_name, doc_sections in grouped_sections.items()
        ]
    }, gnc_evidences


def review_intake_step(step_input: StepInput) -> StepOutput:
    raw = step_input.input
    payload = raw if isinstance(raw, dict) else {"message": str(raw or "")}
    params = payload.get("params") if isinstance(payload.get("params"), dict) else payload
    request = GNCReviewRequest.model_validate(params)

    document_parts: list[str] = []
    documents: list[dict[str, Any]] = []
    for doc in request.documents:
        doc_data = doc.model_dump(mode="json")
        content = _read_document_content(doc_data, metadata=request.metadata)
        doc_data["content"] = content
        documents.append(doc_data)
        document_parts.append(f"=== {doc.name or doc.file_path or 'unnamed'} ===\n{content}")

    if request.mode == GNCReviewMode.SINGLE_DOC and len(documents) != 1:
        raise ValueError("single_doc mode requires exactly one design document")
    if request.mode == GNCReviewMode.MULTI_DOC and len(documents) < 2:
        raise ValueError("multi_doc mode requires at least two design documents")

    review_id = str(payload.get("review_id") or request.metadata.get("review_id") or "")
    metadata = request.metadata if isinstance(request.metadata, dict) else {}
    prior_cycle_context = metadata.get("prior_cycle_context") or {}
    review_focus = request.review_focus or prior_cycle_context
    intake = {
        "step": "review_intake",
        "review_id": review_id,
        "name": request.name,
        "mode": request.mode.value,
        "product_model": request.product_model,
        "review_phase": request.review_phase,
        "review_scope": request.review_scope,
        "review_focus": review_focus,
        "prior_cycle_context": prior_cycle_context,
        "current_cycle": metadata.get("current_cycle", 1),
        "documents": documents,
        "review_rules": [rule.model_dump(mode="json") for rule in request.review_rules],
        "document_text": "\n\n".join(document_parts),
        "document_length": sum(len(doc.get("content", "")) for doc in documents),
        "metadata": request.metadata,
        "timestamp": _now(),
    }
    logger.info("[GNC-Review] intake review_id=%s docs=%d mode=%s", review_id, len(documents), request.mode.value)
    return _as_json(intake)


def document_structuring_step(step_input: StepInput) -> StepOutput:
    intake = _load_json(step_input.previous_step_content)
    existing_struct = _struct_from_existing_bundle(intake)
    if existing_struct is not None:
        section_tree, evidences = existing_struct
        return _as_json(
            {
                "step": "document_structuring",
                "intake_data": intake,
                "section_tree": section_tree,
                "evidence_pool": evidences,
                "structuring_source": "super_agent_structured_bundle",
                "timestamp": _now(),
            }
        )

    from data_agent.parsing.schemas import ParsedDocument
    from data_agent.parsing.structuring.preview_resolution import _build_cached_text_document
    from data_agent.parsing.parse_artifacts import build_structure_artifact

    documents: list[ParsedDocument] = []
    for doc in intake.get("documents", []):
        content = str(doc.get("content") or "").strip()
        if not content:
            continue
        file_name = str(doc.get("name") or Path(str(doc.get("file_path") or "")).name or "document")
        parsed_doc = _build_cached_text_document(
            {
                "name": file_name,
                "content": content,
                "parse_status": "ok",
                "parser_name": "gnc_intake",
            }
        )
        if parsed_doc:
            documents.append(parsed_doc)

    if not documents:
        raise ValueError("document_structuring requires non-empty document content")

    structure = build_structure_artifact(
        {
            "artifact_id": f"gnc-{intake.get('review_id') or 'intake'}",
            "parsed_documents": [{"document": document.model_dump(mode="json")} for document in documents],
            "file_results": [{"file_name": document.file_name, "parse_status": document.parse_status} for document in documents],
            "document_ir": {},
            "warnings": [],
        },
        documents=documents,
    )
    existing_struct = _struct_from_existing_bundle(
        {
            "metadata": {
                "structured_bundle": {
                    "section_tree": structure.section_tree,
                    "evidence_pool": structure.evidence_pool,
                }
            }
        }
    )
    if existing_struct is None:
        raise ValueError("shared structure service produced empty section/evidence artifacts")
    section_tree, evidences = existing_struct

    data = {
        "step": "document_structuring",
        "intake_data": intake,
        "section_tree": section_tree,
        "evidence_pool": evidences,
        "structuring_source": "shared_structure_service",
        "timestamp": _now(),
    }
    return _as_json(data)


_GNC_TASK_BOOK_HINTS = ("任务书", "研制要求", "task_book", "taskbook")
_GNC_RULE_HINTS = ("检查单", "审查规则", "检查需求", "checklist", "产品保证")


def _template_gatekeeping_context(intake: dict[str, Any]) -> dict[str, str | dict | None]:
    """从 intake / metadata 解析 JSON 评审模板门控参数。"""
    metadata = intake.get("metadata") if isinstance(intake.get("metadata"), dict) else {}

    template: dict | None = None
    for source in (intake.get("template"), metadata.get("template"), metadata.get("review_template")):
        if isinstance(source, dict) and source:
            template = source
            break

    template_id = ""
    for candidate in (
        metadata.get("template_id"),
        metadata.get("review_template_id"),
        (template or {}).get("template_id"),
        (template or {}).get("id"),
    ):
        tid = str(candidate or "").strip()
        if tid:
            template_id = tid
            break

    review_phase = str(intake.get("review_phase") or metadata.get("review_phase") or "CDR").strip()
    review_scope = str(intake.get("review_scope") or metadata.get("review_scope") or "ad_ac").strip()
    return {
        "template": template,
        "template_id": template_id,
        "review_phase": review_phase or "CDR",
        "review_scope": review_scope or "ad_ac",
    }


def _evaluate_gnc_package(documents: list[dict[str, Any]], rules: list[dict[str, Any]]) -> dict[str, Any]:
    """GNC 送审包齐套性判定：blocked / limited / passed（需求+任务书+被审文档）。"""
    blocking: list[str] = []
    limited: list[str] = []

    has_subject = any(str(doc.get("content") or "").strip() for doc in documents)
    if not has_subject:
        blocking.append("缺少被审文档正文（送审文档正文为空）")

    def _doc_signal(hints: tuple[str, ...]) -> bool:
        for doc in documents:
            blob = f"{doc.get('name', '')} {doc.get('document_type', '')} {str(doc.get('content') or '')[:400]}".lower()
            if any(hint.lower() in blob for hint in hints):
                return True
        return False

    has_rule = bool(rules) or _doc_signal(_GNC_RULE_HINTS)
    if not has_rule:
        limited.append("未提供检查需求/检查单，按 GNC 通用维度受限审查")

    has_task_book = _doc_signal(_GNC_TASK_BOOK_HINTS)
    if not has_task_book:
        limited.append("未识别任务书/研制要求，承接关系核查受限")

    if blocking:
        status = "blocked"
        summary = f"送审包未齐套：{'；'.join(blocking)}"
    elif limited:
        status = "limited"
        summary = f"送审包可受限启动：{'；'.join(limited)}"
    else:
        status = "passed"
        summary = "送审包齐套性检查通过。"
    return {
        "package_status": status,
        "blocking_reasons": blocking,
        "limited_reasons": limited,
        "summary": summary,
        "can_start_review": status != "blocked",
    }


def quality_screening_step(step_input: StepInput) -> StepOutput:
    struct = _load_json(step_input.previous_step_content)
    intake = struct.get("intake_data", {})
    documents = intake.get("documents", [])
    rules = intake.get("review_rules", [])
    section_tree = struct.get("section_tree", {})
    evidences = struct.get("evidence_pool", [])
    if isinstance(evidences, dict):
        evidences = evidences.get("evidences", []) or []
    missing = []
    warnings = []
    if not any(str(doc.get("content") or "").strip() for doc in documents):
        missing.append("送审文档正文为空")
    if not rules:
        warnings.append("未提供显式审查规则，将按 GNC 通用维度审查")
    if intake.get("mode") == "multi_doc":
        names = [doc.get("name") for doc in documents]
        if len(names) != len(set(names)):
            warnings.append("多文档存在重名材料，跨文档追溯可能不稳定")

    # 送审包齐套性判定（P1）
    package = _evaluate_gnc_package(documents, rules)

    # 信号驱动动态选用 AD/AC 单元 + 模板章节符合性门控（P1）
    corpus_parts = [str(doc.get("content") or "")[:4000] for doc in documents]
    corpus_parts += [f"{ev.get('title', '')} {ev.get('quote', '')}" for ev in evidences]
    corpus = "\n".join(part for part in corpus_parts if part)
    selected_units = select_units_by_signals(corpus)
    gate_ctx = _template_gatekeeping_context(intake)
    template_results = build_unit_template_gatekeeping(
        section_tree,
        evidences,
        units=selected_units,
        template=gate_ctx["template"],  # type: ignore[arg-type]
        template_id=str(gate_ctx["template_id"] or ""),
        subsystem="GNC",
        review_phase=str(gate_ctx["review_phase"] or "CDR"),
        review_scope=str(gate_ctx["review_scope"] or "ad_ac"),
    )
    template_payload = [item.model_dump(mode="json") for item in template_results]
    blocked_units = [item.unit_key for item in template_results if item.status == "hard_fail"]

    score = max(0.0, 1.0 - 0.25 * len(missing) - 0.1 * len(warnings))
    if package["package_status"] == "limited":
        score = max(0.0, score - 0.1)
    data = {
        "step": "quality_screening",
        "intake_data": intake,
        "struct_data": struct,
        "is_reviewable": not missing and package["can_start_review"],
        "missing_items": missing,
        "warnings": warnings,
        "package_gatekeeping": package,
        "template_gatekeeping": template_payload,
        "selected_units": selected_units,
        "blocked_units": blocked_units,
        "quality_scores": {
            "material_completeness": score,
            "rule_readiness": 1.0 if rules else 0.6,
            "cross_document_readiness": 1.0 if intake.get("mode") == "multi_doc" and len(documents) > 1 else 0.8,
        },
        "timestamp": _now(),
    }
    return _as_json(data)


def evidence_pool_building_step(step_input: StepInput) -> StepOutput:
    quality = _load_json(step_input.previous_step_content)
    struct = quality.get("struct_data", {})
    intake = quality.get("intake_data", {})
    unit_evidence_bundles = build_unit_evidence_bundles_for_workflow(
        quality_data=quality,
        section_tree=struct.get("section_tree", {}),
        evidence_pool=struct.get("evidence_pool", []),
        extracted_parameters=list(
            struct.get("extracted_parameters") or quality.get("extracted_parameters") or []
        ),
    )
    quality["unit_evidence_bundles"] = unit_evidence_bundles
    bundles: dict[str, list[str]] = {
        "quality": [],
        "fdir": [],
        "interface": [],
        "simulation": [],
        "ad": [],
        "ac": [],
        "chief": [],
        "editor": [],
    }
    keyword_map = {
        "fdir": ("故障", "隔离", "恢复", "安全模式", "fdir", "fmea"),
        "interface": ("接口", "icd", "总线", "协议", "刷新率", "功耗", "热控", "推进"),
        "simulation": ("验证", "仿真", "试验", "矩阵", "monte", "工况", "覆盖"),
        "quality": ("编号", "术语", "引用", "需求", "设计", "验证", "版本"),
        "ad": ("姿态确定", "定姿", "星敏", "陀螺", "滤波", "指向", "采集时序"),
        "ac": ("姿态控制", "控制律", "执行机构", "飞轮", "推力器", "卸载", "机动", "控制参数"),
    }
    for ev in struct.get("evidence_pool", []):
        text = f"{ev.get('title', '')}\n{ev.get('quote', '')}".lower()
        matched = False
        for discipline, keywords in keyword_map.items():
            if any(keyword.lower() in text for keyword in keywords):
                bundles[discipline].append(ev["evidence_id"])
                matched = True
        if not matched:
            bundles["chief"].append(ev["evidence_id"])
            bundles["editor"].append(ev["evidence_id"])
    data = {
        "step": "evidence_pool_building",
        "quality_data": quality,
        "evidence_pool": struct.get("evidence_pool", []),
        "unit_evidence_bundles": unit_evidence_bundles,
        "unit_evidence_bundle_count": len(unit_evidence_bundles),
        "discipline_evidence_map": bundles,
        "document_text": intake.get("document_text", ""),
        "timestamp": _now(),
    }
    return _as_json(data)


def knowledge_preparation_step(step_input: StepInput) -> StepOutput:
    pool = _load_json(step_input.previous_step_content)
    quality = pool.get("quality_data", {})
    intake = quality.get("intake_data", {})
    rules = intake.get("review_rules", [])
    knowledge_evidence = [
        {
            "evidence_id": f"RULE-{idx:04d}",
            "source_type": "review_rule",
            "rule_id": rule.get("rule_id", ""),
            "title": rule.get("title", ""),
            "quote": rule.get("requirement_text", ""),
            "severity": rule.get("severity", "major"),
        }
        for idx, rule in enumerate(rules, start=1)
    ]
    data = {
        **pool,
        "step": "knowledge_preparation",
        "review_rules": rules,
        "knowledge_evidence": knowledge_evidence,
        "evidences": pool.get("evidence_pool", []) + knowledge_evidence,
        "timestamp": _now(),
    }
    return _as_json(data)


def _specialist_prompt(
    agent_key: str,
    data: dict[str, Any],
    evidence_map: dict[str, dict[str, Any]],
) -> str:
    quality = data.get("quality_data", {})
    intake = quality.get("intake_data", {})
    discipline_map = data.get("discipline_evidence_map", {})
    discipline = agent_key.replace("_specialist", "").replace("_engineer", "")
    ids = set(discipline_map.get(discipline, []) + discipline_map.get("chief", [])[:3])
    if not ids:
        ids = set(list(evidence_map.keys())[:6])
    evidence_subset = [evidence_map[eid] for eid in ids if eid in evidence_map]
    return (
        "请执行 GNC 设计知识型审查，并输出结构化结果。\n"
        f"agent_key={agent_key}\n"
        f"review_id={intake.get('review_id', '')}\n"
        f"mode={intake.get('mode', '')}\n"
        f"product_model={intake.get('product_model', '')}\n"
        f"review_phase={intake.get('review_phase', '')}\n"
        f"quality_screening={json.dumps(quality, ensure_ascii=False)[:2500]}\n"
        f"review_rules={json.dumps(data.get('review_rules', []), ensure_ascii=False)[:4000]}\n"
        f"evidence_subset={json.dumps(evidence_subset, ensure_ascii=False)[:9000]}\n"
        "输出 findings 时 evidence_ids 必须优先使用 evidence_subset 中的 evidence_id。\n"
    )


def _run_committee_agent(
    agent_key: str,
    data: dict[str, Any],
    evidence_map: dict[str, dict[str, Any]],
    model_id: str | None,
    debug_mode: bool,
) -> tuple[str, dict[str, Any], list[dict[str, Any]]]:
    agent = COMMITTEE_AGENT_BUILDERS[agent_key](model_id=model_id, debug_mode=debug_mode)
    output = _run_structured_agent(agent, _specialist_prompt(agent_key, data, evidence_map), GNCCommitteeOutput)
    findings = []
    for finding in output.findings:
        item = finding.model_dump(mode="json")
        item["agent_id"] = item.get("agent_id") or getattr(agent, "id", agent_key)
        item["expert_role"] = item.get("expert_role") or getattr(agent, "name", agent_key)
        item["discipline"] = item.get("discipline") or output.discipline or agent_key
        item["judgment"] = item.get("judgment") or _infer_judgment(item.get("description", ""))
        findings.append(item)
    review = output.model_dump(mode="json")
    review["agent_id"] = getattr(agent, "id", agent_key)
    return agent_key, review, findings


def _run_committee_editor_observer(
    data: dict[str, Any],
    model_id: str | None,
    debug_mode: bool,
) -> tuple[str, dict[str, Any], list[dict[str, Any]]]:
    intake = data.get("quality_data", {}).get("intake_data", {})
    prompt = (
        "你作为 GNC 委员会合稿师先行旁听本轮专家审查准备情况，输出潜在 RID 归并关注点。\n"
        f"review_id={intake.get('review_id', '')}\n"
        f"mode={intake.get('mode', '')}\n"
        f"quality_data={json.dumps(data.get('quality_data', {}), ensure_ascii=False)[:3000]}\n"
        f"review_rules={json.dumps(data.get('review_rules', []), ensure_ascii=False)[:3000]}\n"
    )
    agent = review_editor(model_id=model_id, debug_mode=debug_mode)
    output = _run_structured_agent(agent, prompt, GNCEditorialOutput)
    review = output.model_dump(mode="json")
    review["agent_id"] = getattr(agent, "id", "review_editor")
    review["completed"] = True
    return "review_editor", review, []


def _run_committee_chief_observer(
    data: dict[str, Any],
    model_id: str | None,
    debug_mode: bool,
) -> tuple[str, dict[str, Any], list[dict[str, Any]]]:
    intake = data.get("quality_data", {}).get("intake_data", {})
    prompt = (
        "你作为 GNC 总师先行旁听本轮专家审查准备情况，识别需要重点裁决的审查风险。\n"
        f"review_id={intake.get('review_id', '')}\n"
        f"mode={intake.get('mode', '')}\n"
        f"quality_data={json.dumps(data.get('quality_data', {}), ensure_ascii=False)[:3000]}\n"
        f"review_rules={json.dumps(data.get('review_rules', []), ensure_ascii=False)[:3000]}\n"
    )
    agent = gnc_chief_reviewer(model_id=model_id, debug_mode=debug_mode)
    output = _run_structured_agent(agent, prompt, GNCChiefDecisionOutput)
    review = output.model_dump(mode="json")
    review["agent_id"] = getattr(agent, "id", "gnc_chief_reviewer")
    review["completed"] = True
    return "gnc_chief_reviewer", review, []


def _detect_conflicts(
    findings: list[dict[str, Any]],
    unit_results: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Finding-based opposite judgments plus unit rule expert conflicts (source-compatible facade)."""
    observations: dict[str, list[dict[str, Any]]] = {}
    for finding in findings:
        judgment = finding.get("judgment") or _infer_judgment(finding.get("description", ""))
        if judgment not in {"satisfied", "not_satisfied", "insufficient_evidence"}:
            continue
        keys = [f"rule:{rule_id}" for rule_id in finding.get("rule_ids", []) if rule_id]
        keys += [f"evidence:{evidence_id}" for evidence_id in finding.get("evidence_ids", []) if evidence_id]
        if not keys:
            normalized_title = re.sub(r"\s+", "", str(finding.get("title", ""))).lower()
            if normalized_title:
                keys.append(f"title:{normalized_title[:80]}")
        for key in keys:
            observations.setdefault(key, []).append(
                {
                    "finding_id": finding.get("finding_id", ""),
                    "agent_id": finding.get("agent_id", ""),
                    "discipline": finding.get("discipline", ""),
                    "judgment": judgment,
                    "severity": finding.get("severity", ""),
                    "confidence": finding.get("confidence", 0.0),
                    "summary": _clip(finding.get("description", ""), 240),
                }
            )

    conflicts: list[dict[str, Any]] = []
    for key, items in observations.items():
        judgments = {item["judgment"] for item in items}
        agents = {item["agent_id"] for item in items}
        if len(agents) < 2 or not {"satisfied", "not_satisfied"}.issubset(judgments):
            continue
        ranked = sorted(
            items,
            key=lambda item: (
                _SEVERITY_RANK.get(str(item.get("severity", "")).lower(), 0),
                float(item.get("confidence") or 0.0),
            ),
            reverse=True,
        )
        top = ranked[0]
        runner_up = ranked[1] if len(ranked) > 1 else {}
        can_recommend = (
            _SEVERITY_RANK.get(str(top.get("severity", "")).lower(), 0)
            > _SEVERITY_RANK.get(str(runner_up.get("severity", "")).lower(), 0)
        )
        conflicts.append(
            GNCConflictReport(
                conflict_key=key,
                conflict_type="opposite_expert_judgment",
                summary="同一规则/证据存在专家相反判定",
                observations=ranked,
                recommended_resolution={
                    "selected_judgment": top.get("judgment", ""),
                    "selected_agent_id": top.get("agent_id", ""),
                    "basis": "采信严重度更高且置信度更高的一侧。",
                }
                if can_recommend
                else {},
                requires_arbitration=not can_recommend,
            ).model_dump(mode="json")
        )

    if unit_results:
        for item in detect_expert_opinion_conflicts(unit_results):
            conflicts.append(
                GNCConflictReport(
                    conflict_id=item.get("conflict_id", ""),
                    conflict_key=item.get("conflict_key", ""),
                    conflict_type=item.get("conflict_type", ""),
                    summary=item.get("summary", ""),
                    observations=item.get("observations", []),
                    recommended_resolution=item.get("recommended_resolution", {}),
                    requires_arbitration=bool(item.get("requires_arbitration")),
                ).model_dump(mode="json")
            )
    return conflicts


def _max_review_units() -> int:
    raw = os.getenv("GNC_MAX_REVIEW_UNITS", "12")
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return 12


def _resolve_review_scope(intake_data: dict[str, Any]) -> str:
    """Resolve review_scope from template (preferred) or intake/metadata; default ad_ac."""
    metadata = intake_data.get("metadata") if isinstance(intake_data.get("metadata"), dict) else {}
    scope = str(intake_data.get("review_scope") or metadata.get("review_scope") or "ad_ac").strip().lower()

    template_info: dict[str, Any] | None = None
    for source in (intake_data.get("template"), metadata.get("template"), metadata.get("review_template")):
        if isinstance(source, dict) and source:
            template_info = source
            break

    template_id = ""
    for candidate in (
        metadata.get("template_id"),
        metadata.get("review_template_id"),
        (template_info or {}).get("template_id"),
        (template_info or {}).get("id"),
    ):
        tid = str(candidate or "").strip()
        if tid:
            template_id = tid
            break

    if template_id:
        from data_agent.integrations.satellite_review.review_template_service import resolve_template

        subsystem = str(intake_data.get("subsystem") or metadata.get("subsystem") or "GNC")
        review_phase = str(intake_data.get("review_phase") or metadata.get("review_phase") or "CDR")
        template = resolve_template(subsystem, review_phase, template_id=template_id)
        if isinstance(template, dict) and template.get("review_scope"):
            scope = str(template["review_scope"]).strip().lower()
    elif isinstance(template_info, dict) and template_info.get("review_scope"):
        scope = str(template_info["review_scope"]).strip().lower()

    return scope or "ad_ac"


def _committee_review_via_ad_group(
    intake_data: dict[str, Any],
    knowledge_data: dict[str, Any],
    evidence_map: dict[str, dict[str, Any]],
    *,
    model_id: str | None,
    debug_mode: bool,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    from data_agent.integrations.satellite_review.workflows.ad_review_sub_workflow import (
        run_ad_review_pipeline,
    )

    quality_data = knowledge_data.get("quality_data") or {}
    struct_data = quality_data.get("struct_data") or {}
    findings, conclusion = run_ad_review_pipeline(
        intake_data=intake_data,
        evidences=knowledge_data.get("evidences") or [],
        document_text=str(knowledge_data.get("document_text") or intake_data.get("document_text") or ""),
        model_id=model_id or "",
        struct_data=struct_data,
        unit_evidence_bundles=knowledge_data.get("unit_evidence_bundles"),
        knowledge_data=knowledge_data,
        evidence_map=evidence_map,
        debug_mode=debug_mode,
    )
    review = {
        "discipline": "ad_group",
        "reviewer": "姿态确定专业组",
        "score": float(conclusion.get("confidence_score") or 0.0),
        "summary": conclusion.get("summary", ""),
        "completed": True,
        "verdict": conclusion.get("verdict", "pending"),
    }
    native_result = {
        "conclusion": conclusion,
        "stage_coverage": conclusion.get("stage_coverage", []),
        "unit_results": conclusion.get("unit_results", []),
        "stage_results": conclusion.get("stage_results", {}),
        "blocking_flags": conclusion.get("blocking_flags", []),
    }
    return findings, review, native_result, list(conclusion.get("unit_results") or [])


def _committee_review_via_ac_group(
    intake_data: dict[str, Any],
    knowledge_data: dict[str, Any],
    evidence_map: dict[str, dict[str, Any]],
    *,
    model_id: str | None,
    debug_mode: bool,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    from data_agent.integrations.satellite_review.workflows.ac_review_sub_workflow import (
        run_ac_review_pipeline,
    )

    quality_data = knowledge_data.get("quality_data") or {}
    struct_data = quality_data.get("struct_data") or {}
    findings, conclusion = run_ac_review_pipeline(
        intake_data=intake_data,
        evidences=knowledge_data.get("evidences") or [],
        document_text=str(knowledge_data.get("document_text") or intake_data.get("document_text") or ""),
        model_id=model_id or "",
        struct_data=struct_data,
        unit_evidence_bundles=knowledge_data.get("unit_evidence_bundles"),
        knowledge_data=knowledge_data,
        evidence_map=evidence_map,
        debug_mode=debug_mode,
    )
    review = {
        "discipline": "ac_group",
        "reviewer": "姿态控制专业组",
        "score": float(conclusion.get("confidence_score") or 0.0),
        "summary": conclusion.get("summary", ""),
        "completed": True,
        "verdict": conclusion.get("verdict", "pending"),
    }
    native_result = {
        "conclusion": conclusion,
        "stage_coverage": conclusion.get("stage_coverage", []),
        "unit_results": conclusion.get("unit_results", []),
        "stage_results": conclusion.get("stage_results", {}),
        "blocking_flags": conclusion.get("blocking_flags", []),
        "enabled_stages": conclusion.get("enabled_stages", []),
        "skipped_stages": conclusion.get("skipped_stages", []),
    }
    return findings, review, native_result, list(conclusion.get("unit_results") or [])


def _unit_ids_for_group(group: str) -> set[str]:
    from data_agent.core.domain_registry import review_units_for_domain

    return {
        unit_id
        for unit_id, payload in review_units_for_domain("aerospace_review", group=group).items()
    }


def _scope_excluded_unit_ids(*, run_ad_group: bool = False, run_ac_group: bool = False) -> set[str]:
    """Unit IDs that must not run via committee ``run_unit_review`` when a group sub-workflow owns them."""
    excluded: set[str] = set()
    if run_ad_group:
        excluded |= _unit_ids_for_group("ad")
    if run_ac_group:
        excluded |= _unit_ids_for_group("ac")
    return excluded


def _committee_units(data: dict[str, Any], evidence_map: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Resolve the AD/AC units this committee should run (dynamic, includes hard_fail).

    hard_fail units remain in the committee list; ``run_unit_review`` / ``execute_unit_rules``
    circuit-break to placeholder/block results instead of skipping the unit entirely.
    """
    quality_data = data.get("quality_data", {})
    selected = list(quality_data.get("selected_units") or [])
    if not selected:
        corpus = "\n".join(
            f"{ev.get('title', '')} {ev.get('quote', '')}"
            for ev in evidence_map.values()
        )
        selected = select_units_by_signals(corpus)
    cap = _max_review_units()
    return selected[:cap] if cap else selected


def committee_review_step(step_input: StepInput) -> StepOutput:
    data = _load_json(step_input.previous_step_content)
    evidence_map = {ev["evidence_id"]: ev for ev in data.get("evidences", []) if ev.get("evidence_id")}
    quality_data = data.get("quality_data", {})
    intake_data = quality_data.get("intake_data", {}) or {}
    if not intake_data.get("selected_units") and quality_data.get("selected_units"):
        intake_data = {**intake_data, "selected_units": quality_data.get("selected_units")}
    model_id = intake_data.get("metadata", {}).get("model_id")
    debug_mode = bool(intake_data.get("metadata", {}).get("debug_mode", False))
    review_scope = _resolve_review_scope(intake_data)
    logger.info("[GNC-Review] committee review_scope=%s", review_scope)

    findings: list[dict[str, Any]] = []
    discipline_reviews: dict[str, Any] = {}
    unit_reviews: dict[str, Any] = {}
    failures: dict[str, str] = {}
    ad_group_result: dict[str, Any] = {}
    ac_group_result: dict[str, Any] = {}
    unit_results: list[dict[str, Any]] = []

    run_ad_group = review_scope in ("ad_only", "ad_ac")
    run_ac_group = review_scope in ("ac_only", "ad_ac")
    excluded_unit_ids = _scope_excluded_unit_ids(run_ad_group=run_ad_group, run_ac_group=run_ac_group)

    group_futures: dict[Any, str] = {}
    with ThreadPoolExecutor(max_workers=2) as group_pool:
        if run_ad_group:
            group_futures[
                group_pool.submit(
                    _committee_review_via_ad_group,
                    intake_data,
                    data,
                    evidence_map,
                    model_id=model_id,
                    debug_mode=debug_mode,
                )
            ] = "ad_group"
        if run_ac_group:
            group_futures[
                group_pool.submit(
                    _committee_review_via_ac_group,
                    intake_data,
                    data,
                    evidence_map,
                    model_id=model_id,
                    debug_mode=debug_mode,
                )
            ] = "ac_group"

        for future in as_completed(group_futures):
            group_key = group_futures[future]
            try:
                group_findings, group_review, native_result, group_unit_results = future.result()
            except Exception as exc:
                logger.exception("[GNC-Review] %s sub-workflow failed: %s", group_key, exc)
                failures[group_key] = str(exc)
                continue
            findings.extend(group_findings)
            discipline_reviews[group_key] = group_review
            unit_results.extend(group_unit_results)
            for unit_result in group_unit_results:
                unit_key = str(unit_result.get("unit_key") or "")
                if not unit_key:
                    continue
                unit_reviews[unit_key] = {
                    **unit_result,
                    "agent_id": unit_key,
                    "discipline": group_key.replace("_group", ""),
                    "reviewer": group_review.get("reviewer", group_key),
                    "execution": unit_result.get("execution") or "group_sub_workflow",
                    "findings": unit_result.get("findings") or [],
                    "completed": unit_result.get("status") not in {"blocked", "failed"},
                }
                discipline_reviews[unit_key] = unit_reviews[unit_key]
            if group_key == "ad_group":
                ad_group_result = native_result
            else:
                ac_group_result = native_result

    agent_keys = list(COMMITTEE_AGENT_BUILDERS.keys())
    units = [
        unit
        for unit in _committee_units(data, evidence_map)
        if str(unit.get("unit_id") or "") not in excluded_unit_ids
    ]
    max_workers = len(agent_keys) + len(units) + 2
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures: dict[Any, str] = {
            pool.submit(_run_committee_agent, key, data, evidence_map, model_id, debug_mode): key
            for key in agent_keys
        }
        futures[pool.submit(_run_committee_editor_observer, data, model_id, debug_mode)] = "review_editor"
        futures[pool.submit(_run_committee_chief_observer, data, model_id, debug_mode)] = "gnc_chief_reviewer"
        unit_futures: dict[Any, str] = {
            pool.submit(run_unit_review, unit, data, evidence_map, model_id=model_id, debug_mode=debug_mode):
            str(unit.get("unit_id"))
            for unit in units
        }
        for future in as_completed(futures):
            key = futures[future]
            try:
                agent_key, review, agent_findings = future.result()
            except Exception as exc:
                failures[key] = str(exc)
                continue
            discipline_reviews[agent_key] = review
            findings.extend(agent_findings)
        for future in as_completed(unit_futures):
            unit_id = unit_futures[future]
            try:
                unit_key, review, unit_findings = future.result()
            except Exception as exc:  # run_unit_review degrades internally; guard regardless
                failures[unit_id] = str(exc)
                continue
            unit_reviews[unit_key] = review
            discipline_reviews[unit_key] = review
            findings.extend(unit_findings)
            unit_results.append(
                {
                    "unit_key": unit_key,
                    "unit_name": review.get("reviewer") or unit_key,
                    "agent_id": unit_key,
                    "status": review.get("status", ""),
                    "rule_results": review.get("rule_results") or [],
                    "summary": review.get("summary", ""),
                    "is_blocked": review.get("execution") == "blocked",
                    "confidence": review.get("confidence", 0.0),
                    "evidence_ids": review.get("evidence_ids") or [],
                    "findings": review.get("findings") or [],
                }
            )

    for key, error in failures.items():
        discipline_reviews[key] = {
            "agent_id": key,
            "status": "failed",
            "error": error,
            "completed": False,
            "findings": [],
        }

    conflicts = _detect_conflicts(findings, unit_results)
    is_blocked = any(item.get("is_blocked") for item in unit_results if isinstance(item, dict))
    selected_units = list(quality_data.get("selected_units") or [])
    review_focus = intake_data.get("review_focus") or intake_data.get("prior_cycle_context") or {}
    result = {
        "step": "committee_review",
        "review_id": intake_data.get("review_id", ""),
        "current_cycle": intake_data.get("current_cycle", 1),
        "review_scope": review_scope,
        "review_focus": review_focus,
        "prior_cycle_context": intake_data.get("prior_cycle_context") or review_focus,
        "discipline_reviews": discipline_reviews,
        "unit_reviews": unit_reviews,
        "ad_group_result": ad_group_result,
        "ac_group_result": ac_group_result,
        "unit_results": unit_results,
        "selected_units": [
            {
                "unit_id": unit.get("unit_id"),
                "unit_group": unit.get("unit_group"),
                "matched_signals": unit.get("matched_signals", []),
            }
            for unit in selected_units
        ],
        "findings": findings,
        "evidences": data.get("evidences", []),
        "conflicts": conflicts,
        "failures": failures,
        "status": "degraded" if failures else "ok",
        "is_blocked": is_blocked,
        "knowledge_data": data,
        "timestamp": _now(),
    }
    return _as_json(result)


def editorial_synthesis_step(step_input: StepInput) -> StepOutput:
    committee = _load_json(step_input.previous_step_content)
    intake = committee.get("knowledge_data", {}).get("quality_data", {}).get("intake_data", {})
    review_id = str(committee.get("review_id") or intake.get("review_id") or "")
    findings = list(committee.get("findings", []) or [])
    review_focus = committee.get("review_focus") or committee.get("prior_cycle_context") or intake.get("review_focus") or {}
    rule_rid_candidates = build_rule_rid_candidates(committee, findings)
    _, evidence_map, _ = build_trace_context(committee)
    unit_results = list(committee.get("unit_results", []) or [])
    unit_summary = summarize_unit_results(unit_results)
    compact_review_focus = (
        {
            "current_cycle": review_focus.get("current_cycle"),
            "previous_cycle": review_focus.get("previous_cycle"),
            "change_summary": review_focus.get("change_summary", ""),
            "claimed_resolved_rid_ids": review_focus.get("claimed_resolved_rid_ids", []),
            "focus_rid_ids": review_focus.get("focus_rid_ids", []),
            "severe_open_rids": (review_focus.get("severe_open_rids") or [])[:20],
        }
        if isinstance(review_focus, dict)
        else {}
    )
    prompt = (
        "请将 GNC 专家审查 findings 合稿为 RID 清单、纪要和结论草案。\n"
        "not_satisfied / insufficient_evidence 规则候选为强候选；若来自规则候选，保留 source_type=rule_judgment 及 source_rule_id/source_rule_judgment。\n"
        "如果本轮是复审，必须优先对照 review_focus 中的历史 RID：区分“已验证关闭、仍未解决、本轮新增问题”。\n"
        f"review_id={review_id}\n"
        f"findings={json.dumps(committee.get('findings', []), ensure_ascii=False)[:10000]}\n"
        f"conflicts={json.dumps(committee.get('conflicts', []), ensure_ascii=False)[:5000]}\n"
        f"rule_candidates={json.dumps(rule_rid_candidates[:120], ensure_ascii=False)[:6000]}\n"
        f"unit_summary={json.dumps(unit_summary, ensure_ascii=False)}\n"
        f"review_focus={json.dumps(compact_review_focus, ensure_ascii=False)}\n"
        f"unit_results={json.dumps(unit_results[:20], ensure_ascii=False)[:4000]}\n"
    )
    agent = review_editor(
        model_id=intake.get("metadata", {}).get("model_id"),
        debug_mode=bool(intake.get("metadata", {}).get("debug_mode", False)),
    )
    output = _run_structured_agent_or_fallback(
        agent,
        prompt,
        GNCEditorialOutput,
        fallback=lambda reason: _fallback_editorial_from_committee(committee, reason=reason),
    )
    editorial_payload = output.model_dump(mode="json")
    rid_items, _, appended_rule_count = merge_editorial_rid_items(
        review_id,
        editorial_payload.get("rid_items", []),
        rule_rid_candidates,
        findings,
        evidence_map,
    )
    rid_items, prior_cycle_summary = annotate_rid_prior_cycle_status(rid_items, review_focus)
    editorial_payload["rid_items"] = rid_items
    editorial_payload["rule_rid_candidate_count"] = len(rule_rid_candidates)
    editorial_payload["rule_rid_appended_count"] = appended_rule_count

    struct_data = (
        committee.get("knowledge_data", {})
        .get("quality_data", {})
        .get("struct_data", {})
    )
    traceability_matrix_summary = struct_data.get("traceability_matrix_summary") or {}
    minutes_struct = build_editorial_minutes_struct(
        review_id=review_id,
        product_model=str(intake.get("product_model", "")),
        review_phase=str(intake.get("review_phase", "")),
        rid_items=rid_items,
        discipline_reviews=committee.get("discipline_reviews", {}),
        unit_results=unit_results,
        editorial_result=editorial_payload,
        section_tree=struct_data.get("section_tree") if isinstance(struct_data, dict) else {},
        traceability_matrix_summary=traceability_matrix_summary if isinstance(traceability_matrix_summary, dict) else {},
        evidences=committee.get("evidences", []),
        appended_rule_count=appended_rule_count,
        generated_at=_now(),
        prior_cycle_summary=prior_cycle_summary,
    )
    editorial_payload["minutes_struct"] = minutes_struct
    editorial_payload["section_rid_map"] = minutes_struct.get("section_rid_map", {})
    editorial_payload["rule_coverage_summary"] = minutes_struct.get("rule_coverage_summary", {})
    editorial_payload["unit_review_summary"] = minutes_struct.get("unit_review_summary", {})
    editorial_payload["traceability_matrix_summary"] = minutes_struct.get("traceability_matrix_summary", {})
    editorial_payload["prior_cycle_summary"] = prior_cycle_summary
    editorial_payload["committee_members"] = minutes_struct.get("committee_members", [])

    llm_minutes = str(editorial_payload.get("minutes", "")).strip()
    if llm_minutes:
        editorial_payload["minutes"] = llm_minutes
    else:
        editorial_payload["minutes"] = str(minutes_struct.get("conclusion_draft", "") or editorial_payload.get("conclusion_draft", ""))
    if appended_rule_count and "规则判定" not in editorial_payload["minutes"]:
        editorial_payload["minutes"] = (
            editorial_payload["minutes"]
            + f"\n\n另有 {appended_rule_count} 条由规则判定直接提升的整改项。"
        ).strip()

    result = {
        "step": "editorial_synthesis",
        "review_id": review_id,
        "committee_data": committee,
        "editorial_synthesis": editorial_payload,
        "rid_items": rid_items,
        "findings": findings,
        "evidences": committee.get("evidences", []),
        "minutes": minutes_struct,
        "traceability_matrix_summary": minutes_struct.get("traceability_matrix_summary", {}),
        "discipline_reviews": committee.get("discipline_reviews", {}),
        "unit_results": unit_results,
        "prior_cycle_context": review_focus,
        "review_focus": review_focus,
        "timestamp": _now(),
    }
    return _as_json(result)


def chief_adjudication_step(step_input: StepInput) -> StepOutput:
    editorial = _load_json(step_input.previous_step_content)
    committee = editorial.get("committee_data", {})
    intake = committee.get("knowledge_data", {}).get("quality_data", {}).get("intake_data", {})
    unit_results = editorial.get("unit_results") or committee.get("unit_results") or []
    review_focus = editorial.get("review_focus") or editorial.get("prior_cycle_context") or {}
    expert_conflicts = detect_expert_opinion_conflicts(unit_results)
    risk_summary = summarize_review_risk_categories(unit_results)
    prompt = (
        "请基于 GNC 专家 findings、冲突报告和合稿清单给出总师审定结论。\n"
        "若同一规则/证据出现 satisfied 与 not_satisfied，按 arbitration_score 与 deterministic_checked 优先级裁决；"
        "score gap < 0.12 且无法裁决时 requires_arbitration=true。\n"
        "若本轮为复审，应优先判断上一轮声明已整改 RID 是否可关闭、是否仍未解决、是否引入新风险。\n"
        f"review_id={intake.get('review_id', '')}\n"
        f"findings={json.dumps(committee.get('findings', []), ensure_ascii=False)[:9000]}\n"
        f"conflicts={json.dumps(committee.get('conflicts', []), ensure_ascii=False)[:5000]}\n"
        f"expert_conflicts={json.dumps(expert_conflicts, ensure_ascii=False)[:6000]}\n"
        f"risk_summary={json.dumps(risk_summary, ensure_ascii=False)}\n"
        f"review_focus={json.dumps(review_focus, ensure_ascii=False)[:4000]}\n"
        f"editorial={json.dumps(editorial.get('editorial_synthesis', {}), ensure_ascii=False)[:6000]}\n"
        f"unit_results={json.dumps(unit_results[:20], ensure_ascii=False)[:5000]}\n"
    )
    agent = gnc_chief_reviewer(
        model_id=intake.get("metadata", {}).get("model_id"),
        debug_mode=bool(intake.get("metadata", {}).get("debug_mode", False)),
    )
    editorial_payload = editorial.get("editorial_synthesis", {})
    output = _run_structured_agent_or_fallback(
        agent,
        prompt,
        GNCChiefDecisionOutput,
        fallback=lambda reason: _fallback_chief_from_committee(
            committee,
            editorial_payload if isinstance(editorial_payload, dict) else {},
            reason=reason,
        ),
    )
    decision = apply_chief_arbitration(
        output.model_dump(mode="json"),
        expert_conflicts=expert_conflicts,
        committee_conflicts=committee.get("conflicts") or [],
        failures=committee.get("failures") or {},
    )
    result = {
        "step": "chief_adjudication",
        "review_id": editorial.get("review_id") or intake.get("review_id", ""),
        "editorial_data": editorial,
        "chief_decision": decision,
        "expert_conflicts": expert_conflicts,
        "rid_items": editorial.get("rid_items") or editorial.get("editorial_synthesis", {}).get("rid_items", []),
        "findings": editorial.get("findings") or committee.get("findings", []),
        "evidences": editorial.get("evidences") or committee.get("evidences", []),
        "minutes": editorial.get("minutes") or editorial.get("editorial_synthesis", {}).get("minutes_struct", {}),
        "discipline_reviews": editorial.get("discipline_reviews") or committee.get("discipline_reviews", {}),
        "review_focus": review_focus,
        "prior_cycle_context": review_focus,
        "unit_results": unit_results,
        "timestamp": _now(),
    }
    return _as_json(result)


def human_arbitration_step(step_input: StepInput) -> StepOutput:
    chief = _load_json(step_input.previous_step_content)
    decision = chief.get("chief_decision", {})
    arbitration_items = list(decision.get("arbitration_items", []) or [])
    result = {
        "step": "human_arbitration",
        "review_id": chief.get("review_id", ""),
        "chief_data": chief,
        "requires_arbitration": bool(decision.get("requires_arbitration")),
        "arbitration_status": "pending" if decision.get("requires_arbitration") else "not_required",
        "arbitration_items": arbitration_items,
        "expert_conflicts": chief.get("expert_conflicts", []),
        "timestamp": _now(),
    }
    return _as_json(result)


def review_closure_step(step_input: StepInput) -> StepOutput:
    arbitration = _load_json(step_input.previous_step_content)
    chief = arbitration.get("chief_data", {})
    editorial = chief.get("editorial_data", {})
    committee = editorial.get("committee_data", {})
    knowledge = committee.get("knowledge_data", {})
    quality = knowledge.get("quality_data", {})
    intake = quality.get("intake_data", {})
    status = (
        GNCReviewStatus.ARBITRATION_PENDING
        if arbitration.get("requires_arbitration")
        else GNCReviewStatus.COMPLETED
    )
    structured_bundle_for_meta = intake.get("metadata", {}).get("structured_bundle") or {}
    parse_artifact = structured_bundle_for_meta.get("parse_artifact") or {}
    batch_summary = parse_artifact.get("batch_summary") or {}
    limited_review = bool(
        batch_summary.get("degraded_count")
        or batch_summary.get("failed_count")
        or committee.get("failures")
    )
    editorial_payload = editorial.get("editorial_synthesis", {}) or {}
    rid_items = editorial.get("rid_items") or editorial_payload.get("rid_items") or []
    open_rids = [item for item in rid_items if isinstance(item, dict) and item.get("status", "open") == "open"]
    has_open_major = any(
        str(item.get("severity", "")).lower() in ("critical", "major") for item in open_rids
    )
    result = GNCReviewResult(
        review_id=intake.get("review_id", ""),
        mode=GNCReviewMode(intake.get("mode", "single_doc")),
        status=status,
        findings=[GNCExpertFinding.model_validate(item) for item in committee.get("findings", [])],
        evidence=committee.get("evidences", []),
        conflicts=[GNCConflictReport.model_validate(item) for item in committee.get("conflicts", [])],
        quality_scores=quality.get("quality_scores", {}),
        discipline_reviews=committee.get("discipline_reviews", {}),
        editorial_synthesis=editorial.get("editorial_synthesis", {}),
        chief_decision=chief.get("chief_decision", {}),
        arbitration=arbitration,
        report_markdown="",
        metadata={
            "completed_at": _now(),
            "degraded": limited_review,
            "limited_review": limited_review,
            "parse_batch_summary": batch_summary,
            "committee_failures": committee.get("failures", {}),
            "open_rid_count": len(open_rids),
            "requires_re_review": has_open_major,
            "prior_cycle_summary": editorial_payload.get("prior_cycle_summary", {}),
            "traceability_matrix_summary": editorial_payload.get("traceability_matrix_summary", {}),
            "section_rid_map": editorial_payload.get("section_rid_map", {}),
            "rule_coverage_summary": editorial_payload.get("rule_coverage_summary", {}),
            "unit_review_summary": editorial_payload.get("unit_review_summary", {}),
            "review_focus": editorial.get("review_focus") or committee.get("review_focus") or {},
        },
    )
    from data_agent.reporting import ReviewReportInput, build_review_report

    structured_bundle = structured_bundle_for_meta
    if not structured_bundle:
        structured_bundle = {
            "section_tree": knowledge.get("struct_data", {}).get("section_tree", {}),
            "evidence_pool": {"evidences": committee.get("evidences", [])},
            "materials": intake.get("documents", []),
            "stats": {
                "document_count": len(intake.get("documents", []) or []),
                "evidence_count": len(committee.get("evidences", []) or []),
                "finding_count": len(committee.get("findings", []) or []),
            },
            "warnings": quality.get("warnings", []),
        }
    artifact = build_review_report(
        ReviewReportInput(
            report_id=f"gnc-{result.review_id or 'review'}",
            review_type="gnc_review",
            audience="user",
            structured_bundle=structured_bundle,
            review_results={"gnc_review_result": result.model_dump(mode="json")},
            quality_report={
                **(quality.get("quality_scores") if isinstance(quality.get("quality_scores"), dict) else {}),
                "template_gatekeeping": quality.get("template_gatekeeping"),
                "package_gatekeeping": quality.get("package_gatekeeping"),
                "is_reviewable": quality.get("is_reviewable"),
                "missing_items": quality.get("missing_items"),
                "warnings": quality.get("warnings"),
            },
            metadata={
                "title": "GNC 设计文档审查报告",
                "review_id": result.review_id,
                "product_model": intake.get("product_model", ""),
                "review_phase": intake.get("review_phase", ""),
                "review_scope": intake.get("review_scope", ""),
                "objective": intake.get("name", ""),
            },
        )
    )
    result.report_markdown = artifact.markdown
    result.metadata["report_artifact"] = artifact.model_dump(mode="json")
    return _as_json({"step": "review_closure", "result": result.model_dump(mode="json"), "timestamp": _now()})


def _render_report_markdown(
    intake: dict[str, Any],
    committee: dict[str, Any],
    editorial: dict[str, Any],
    chief: dict[str, Any],
    arbitration: dict[str, Any],
) -> str:
    decision = chief.get("chief_decision", {})
    lines = [
        f"# GNC 设计审查报告 - {intake.get('review_id', '')}",
        "",
        f"- 模式: {intake.get('mode', '')}",
        f"- 型号: {intake.get('product_model', '')}",
        f"- 审查阶段: {intake.get('review_phase', '')}",
        f"- 总师结论: {resolve_verdict_label_zh(str(decision.get('verdict') or ''))}",
        f"- 是否需人工仲裁: {arbitration.get('requires_arbitration', False)}",
        "",
        "## 总师依据",
        decision.get("rationale", ""),
        "",
        "## 主要 Findings",
    ]
    for finding in committee.get("findings", [])[:30]:
        lines.append(f"- [{finding.get('severity', '')}] {finding.get('title', '')}: {finding.get('description', '')}")
    lines.extend(["", "## 合稿纪要", editorial.get("editorial_synthesis", {}).get("minutes", "")])
    return "\n".join(lines)


GNC_WORKFLOW_STEPS = [
    "review_intake",
    "document_structuring",
    "quality_screening",
    "evidence_pool_building",
    "knowledge_preparation",
    "committee_review",
    "editorial_synthesis",
    "chief_adjudication",
    "human_arbitration",
    "review_closure",
]


def get_gnc_design_review_workflow(
    model_id: str | None = None,
    user_id: str | None = None,
    session_id: str | None = None,
    debug_mode: bool = True,
    **kwargs: Any,
) -> Workflow:
    del model_id, user_id, session_id, debug_mode, kwargs
    return Workflow(
        id="data_agent:gnc_design_review_workflow",
        name="GNC 知识型专家设计审查",
        description="Evidence -> Finding -> RID -> Minutes -> Decision 的 GNC 设计审查 workflow。",
        steps=[
            Step(name="review_intake", executor=review_intake_step, description="送审材料接收"),
            Step(name="document_structuring", executor=document_structuring_step, description="文档结构化"),
            Step(name="quality_screening", executor=quality_screening_step, description="材料质量筛查"),
            Step(name="evidence_pool_building", executor=evidence_pool_building_step, description="证据池装配"),
            Step(name="knowledge_preparation", executor=knowledge_preparation_step, description="知识上下文准备"),
            Step(name="committee_review", executor=committee_review_step, description="多专家并行审查与冲突检测"),
            Step(name="editorial_synthesis", executor=editorial_synthesis_step, description="合稿归并"),
            Step(name="chief_adjudication", executor=chief_adjudication_step, description="总师审定"),
            Step(name="human_arbitration", executor=human_arbitration_step, description="人工仲裁条件分支"),
            Step(name="review_closure", executor=review_closure_step, description="审查闭环"),
        ],
    )


def _partial_gnc_result_from_steps(
    step_outputs: dict[str, Any],
    *,
    review_id: str,
    error: str,
) -> GNCReviewResult:
    """Return committee findings when a late-step failure would otherwise drop all results."""
    committee = step_outputs.get("committee_review") or {}
    intake = (
        committee.get("knowledge_data", {})
        .get("quality_data", {})
        .get("intake_data", {})
    )
    editorial = step_outputs.get("editorial_synthesis", {}).get("editorial_synthesis")
    if not editorial:
        editorial = _fallback_editorial_from_committee(committee, reason=error)
        review_id = str(intake.get("review_id") or review_id)
        findings = list(committee.get("findings", []) or [])
        rule_rid_candidates = build_rule_rid_candidates(committee, findings)
        _, evidence_map, _ = build_trace_context(committee)
        rid_items, _, _ = merge_editorial_rid_items(
            review_id,
            editorial.get("rid_items", []),
            rule_rid_candidates,
            findings,
            evidence_map,
        )
        editorial = {**editorial, "rid_items": rid_items}
    chief = step_outputs.get("chief_adjudication", {}).get("chief_decision") or _fallback_chief_from_committee(
        committee,
        editorial if isinstance(editorial, dict) else {},
        reason=error,
    )
    return GNCReviewResult(
        review_id=str(intake.get("review_id") or review_id),
        mode=GNCReviewMode(str(intake.get("mode", "single_doc"))),
        status=GNCReviewStatus.COMPLETED,
        findings=[GNCExpertFinding.model_validate(item) for item in committee.get("findings", [])],
        evidence=committee.get("evidences", []),
        conflicts=[GNCConflictReport.model_validate(item) for item in committee.get("conflicts", [])],
        discipline_reviews=committee.get("discipline_reviews", {}),
        editorial_synthesis=editorial if isinstance(editorial, dict) else {},
        chief_decision=chief if isinstance(chief, dict) else {},
        arbitration={"requires_arbitration": False, "arbitration_status": "not_required"},
        metadata={
            "degraded": True,
            "limited_review": True,
            "partial_closure": True,
            "error": error,
        },
    )


def run_gnc_design_review(request: GNCReviewRequest, *, review_id: str) -> tuple[GNCReviewResult, dict[str, Any]]:
    """Execute the GNC review steps synchronously; late-step failures still return committee findings."""
    previous_content: str | None = None
    step_outputs: dict[str, Any] = {}
    initial_input = {"review_id": review_id, "params": request.model_dump(mode="json")}
    step_executors = [
        ("review_intake", review_intake_step),
        ("document_structuring", document_structuring_step),
        ("quality_screening", quality_screening_step),
        ("evidence_pool_building", evidence_pool_building_step),
        ("knowledge_preparation", knowledge_preparation_step),
        ("committee_review", committee_review_step),
        ("editorial_synthesis", editorial_synthesis_step),
        ("chief_adjudication", chief_adjudication_step),
        ("human_arbitration", human_arbitration_step),
        ("review_closure", review_closure_step),
    ]
    try:
        for step_name, executor in step_executors:
            step_input = StepInput(
                input=initial_input if previous_content is None else None,
                previous_step_content=previous_content,
            )
            output = executor(step_input)
            previous_content = str(output.content or "")
            step_outputs[step_name] = _load_json(previous_content)
    except Exception as exc:
        if "committee_review" not in step_outputs:
            raise
        logger.warning("gnc_workflow_partial_closure review_id=%s error=%s", review_id, exc)
        partial = _partial_gnc_result_from_steps(step_outputs, review_id=review_id, error=str(exc))
        step_outputs["review_closure"] = {"result": partial.model_dump(mode="json"), "partial": True}
        return partial, step_outputs
    result = GNCReviewResult.model_validate(step_outputs["review_closure"]["result"])
    return result, step_outputs


__all__ = [
    "GNC_WORKFLOW_STEPS",
    "committee_review_step",
    "get_gnc_design_review_workflow",
    "run_gnc_design_review",
]
