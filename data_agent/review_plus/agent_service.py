"""Agent-backed helpers for the Review-Plus workflow.

The deterministic services remain the fallback path. These helpers mirror the
old GNC review workflow pattern: cached Agno agents, output_schema validation,
and compact prompts built from already parsed task data.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Literal

from pydantic import BaseModel, Field

from data_agent.review_plus.schemas import (
    ReviewPlusCheckItem,
    ReviewPlusReport,
    ReviewPlusSectionMapping,
)

logger = logging.getLogger(__name__)

_agents: dict[str, Any] = {}


def _should_use_json_mode() -> bool:
    """GLM/Qwen OpenAI-compatible endpoints need json_object mode for output_schema."""
    from data_agent.core.llm_profiles import get_llm_profile

    profile = get_llm_profile("general")
    model_name = (profile.model or "").lower()
    base_url = (profile.base_url or "").lower()
    if "glm" in model_name or "qwen" in model_name:
        return True
    for hint in ("bigmodel.cn", "dashscope", "siliconflow", "modelscope"):
        if hint in base_url:
            return True
    return False


def _agents_enabled() -> bool:
    return os.getenv("REVIEW_PLUS_AGENTS_ENABLED", "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def _get_agent(agent_key: str, *, name: str, output_schema: type[BaseModel], instructions: list[str]) -> Any:
    if not _agents_enabled():
        raise RuntimeError("Review-Plus Agent enhancement disabled by REVIEW_PLUS_AGENTS_ENABLED")
    if agent_key in _agents:
        return _agents[agent_key]

    from agno.agent import Agent
    from data_agent.agno_structured import build_agent_kwargs, probe_provider_capabilities

    model_id = os.getenv("REVIEW_PLUS_LLM_MODEL_ID")
    cap = probe_provider_capabilities(role="general")
    agent_kwargs = build_agent_kwargs(
        cap,
        id=f"aero:review_plus_{agent_key}",
        name=name,
        output_schema=output_schema,
        instructions=instructions,
        model_id=model_id,
        debug_mode=False,
    )
    _agents[agent_key] = Agent(**agent_kwargs)
    return _agents[agent_key]


def _normalize_structured_payload(payload: Any, schema: type[BaseModel]) -> Any:
    if isinstance(payload, list):
        field_names = list(schema.model_fields.keys())
        if len(field_names) == 1:
            return {field_names[0]: payload}
        if payload and isinstance(payload[0], dict):
            if "check_item_id" in payload[0] and "mappings" in schema.model_fields:
                return {"mappings": payload}
            if "name" in payload[0] and "materials" in schema.model_fields:
                return {"materials": payload}
            if "title" in payload[0] and "items" in schema.model_fields:
                return {"items": payload}
    return payload


def _content_as_model(response: Any, schema: type[BaseModel]) -> BaseModel:
    from data_agent.agno_structured import validate_structured_output

    payload = getattr(response, "content", response)
    return validate_structured_output(payload, schema, payload_normalizer=_normalize_structured_payload)


def _run_agent_structured(agent: Any, prompt: str, schema: type[BaseModel]) -> BaseModel:
    from data_agent.agno_structured import run_agent_with_validation

    return run_agent_with_validation(
        agent,
        prompt,
        schema,
        payload_normalizer=_normalize_structured_payload,
    )


def _material_sample(material: Any, *, max_chars: int = 1400) -> dict[str, Any]:
    role = getattr(material, "role", "")
    return {
        "name": getattr(material, "name", ""),
        "file_type": getattr(material, "file_type", ""),
        "parser_name": getattr(material, "parser_name", ""),
        "parse_status": getattr(material, "parse_status", ""),
        "current_role": role.value if hasattr(role, "value") else str(role or ""),
        "current_confidence": float(getattr(material, "role_confidence", 0.0) or 0.0),
        "current_reason": getattr(material, "role_reason", ""),
        "content_sample": (getattr(material, "content", "") or "")[:max_chars],
    }


class MaterialClassificationItem(BaseModel):
    name: str = ""
    role: Literal[
        "review_rule",
        "checklist",
        "task_book",
        "subject_report",
        "subject_document",
        "supporting_attachment",
        "unknown",
    ] = "unknown"
    confidence: float = 0.0
    reason: str = ""


class MaterialClassificationOutput(BaseModel):
    materials: list[MaterialClassificationItem] = Field(default_factory=list)


class ScenarioDetectionOutput(BaseModel):
    scenario: str = "generic_document_package_review"
    confidence: float = 0.0
    reason: str = ""


class ExtractedCheckItem(BaseModel):
    item_no: str = ""
    title: str = ""
    requirement_text: str = ""
    acceptance_criteria: str = ""
    applicable_scope: str = ""
    severity: Literal["critical", "major", "minor", "info"] = "minor"
    category: str = ""
    source_quote: str = ""
    confidence: float = 0.0


class RuleExtractionOutput(BaseModel):
    check_items: list[ExtractedCheckItem] = Field(default_factory=list)


class MappingItem(BaseModel):
    check_item_id: str = ""
    evidence_ids: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    rationale: str = ""


class EvidenceMappingOutput(BaseModel):
    mappings: list[MappingItem] = Field(default_factory=list)


class CrossDocumentReviewItem(BaseModel):
    item_type: str = "cross_document_issue"
    severity: Literal["critical", "major", "minor", "info"] = "major"
    title: str = ""
    description: str = ""
    impact: str = ""
    recommendation: str = ""
    source_quote: str = ""


class CrossDocumentReviewOutput(BaseModel):
    items: list[CrossDocumentReviewItem] = Field(default_factory=list)


class ReportCompositionOutput(BaseModel):
    conclusion: str = ""
    summary: str = ""
    residual_risks: list[str] = Field(default_factory=list)
    cross_references: list[dict[str, Any]] = Field(default_factory=list)


def detect_scenario_with_agent(materials: list[Any], fallback: dict[str, Any]) -> dict[str, Any]:
    try:
        agent = _get_agent(
            "scenario_detector",
            name="Review-Plus 审查场景识别",
            output_schema=ScenarioDetectionOutput,
            instructions=[
                "你是航天审查场景识别专家，根据材料包判断适用审查场景。",
                "scenario 使用稳定英文标识，reason 用中文说明材料依据。",
                "若无法识别专门场景，使用 generic_document_package_review。",
            ],
        )
        prompt = (
            "请识别 Review-Plus 材料包的审查场景，并给出置信度。\n"
            f"rule_based_hint={json.dumps(fallback, ensure_ascii=False)}\n"
            f"materials={json.dumps([_material_sample(m, max_chars=900) for m in materials], ensure_ascii=False)}"
        )
        output = _run_agent_structured(agent, prompt, ScenarioDetectionOutput)
        return {
            "scenario": output.scenario or fallback.get("scenario", ""),
            "confidence": max(0.0, min(float(output.confidence or 0.0), 1.0)),
            "reason": output.reason or fallback.get("reason", ""),
        }
    except Exception as exc:
        logger.warning("[ReviewPlusAgent] scenario detection failed: %s", exc)
        return fallback


def extract_check_items_with_agent(material: Any, deterministic_items: list[ReviewPlusCheckItem]) -> list[ReviewPlusCheckItem] | None:
    if not deterministic_items:
        return None
    try:
        agent = _get_agent(
            "rule_extractor",
            name="Review-Plus 检查项抽取",
            output_schema=RuleExtractionOutput,
            instructions=[
                "你是航天审查规则结构化专家，负责从规则文档、检查单或检查需求中抽取检查项。",
                "只抽取真实检查要求，跳过封面、目录、签署页和说明文字。",
                "每条检查项必须保留原文依据 source_quote；不要编造文档中不存在的要求。",
            ],
        )
        
        # 引入滑动窗口分批提交机制 (Sliding-Window Batching)
        batch_size = 20
        all_extracted_items = []
        
        for i in range(0, len(deterministic_items), batch_size):
            slice_items = deterministic_items[i : i + batch_size]
            batch_no = i // batch_size + 1
            prompt = (
                f"请基于材料正文和规则解析结果（第 {batch_no} 批），抽取/校正结构化检查项。\n"
                "输出必须是 JSON 对象，格式为 {\"check_items\": [...]}，不要直接返回数组。\n"
                "如果规则解析结果已经合理，可归并重复项并补全字段。\n"
                f"material={json.dumps(_material_sample(material, max_chars=8000), ensure_ascii=False)}\n"
                f"deterministic_items={json.dumps([item.model_dump() for item in slice_items], ensure_ascii=False)}"
            )
            try:
                output = _run_agent_structured(agent, prompt, RuleExtractionOutput)
            except Exception as batch_exc:
                logger.warning(
                    "[ReviewPlusAgent] rule extraction batch %s failed for %s: %s",
                    batch_no,
                    getattr(material, "name", ""),
                    batch_exc,
                )
                continue
            
            for raw in output.check_items:
                title = (raw.title or "").strip()
                requirement = (raw.requirement_text or "").strip()
                if not title and not requirement:
                    continue
                all_extracted_items.append(ReviewPlusCheckItem(
                    item_no=raw.item_no,
                    title=title,
                    requirement_text=requirement,
                    acceptance_criteria=raw.acceptance_criteria,
                    applicable_scope=raw.applicable_scope,
                    severity=raw.severity or "minor",
                    category=raw.category,
                    source_material_name=getattr(material, "name", ""),
                    source_quote=raw.source_quote or requirement or title,
                    confidence=max(0.0, min(float(raw.confidence or 0.0), 1.0)),
                ))
                
        return all_extracted_items or None
    except Exception as exc:
        logger.warning("[ReviewPlusAgent] rule extraction failed for %s: %s", getattr(material, "name", ""), exc)
        return None


def refine_mappings_with_agent(
    check_items: list[ReviewPlusCheckItem],
    keyword_mappings: list[ReviewPlusSectionMapping],
) -> list[ReviewPlusSectionMapping] | None:
    if not check_items or not keyword_mappings:
        return keyword_mappings
    mapping_by_id = {mapping.check_item_id: mapping for mapping in keyword_mappings}
    evidence_catalog: dict[str, dict[str, Any]] = {}
    compact_candidates = []
    
    # 引入层次化语义预检索过滤 (Hierarchical Pre-retrieval Filter)
    # 对 check_items 与已候选章节进行基于关键词和局部相似性的精简，仅推送 Top-3 相关段落
    for item in check_items[:80]:
        mapping = mapping_by_id.get(item.check_item_id)
        candidates = []
        if mapping:
            raw_candidates = []
            for evidence_id, quote, title, section_id in zip(
                mapping.evidence_ids,
                mapping.evidence_quotes,
                mapping.section_titles,
                mapping.section_ids,
            ):
                evidence_catalog[evidence_id] = {
                    "evidence_id": evidence_id,
                    "section_id": section_id,
                    "section_title": title,
                    "quote": quote,
                }
                
                # 计算粗筛匹配度得分（基于 CheckItem 标题/要求的关键词交集）
                q_lower = quote.lower()
                title_lower = (item.title or "").lower()
                req_lower = (item.requirement_text or "").lower()
                score = sum(1 for word in title_lower.split() if len(word) > 1 and word in q_lower)
                score += sum(2 for word in req_lower.split() if len(word) > 1 and word in q_lower)
                
                raw_candidates.append({
                    "evidence_id": evidence_id,
                    "section_title": title,
                    "quote": quote,
                    "score": score
                })
            
            # 按匹配得分排序，保留最相关的 Top-3 段落推送给 Agent
            sorted_candidates = sorted(raw_candidates, key=lambda x: x["score"], reverse=True)[:3]
            for candidate in sorted_candidates:
                candidates.append({
                    "evidence_id": candidate["evidence_id"],
                    "section_title": candidate["section_title"],
                    "quote": candidate["quote"][:700],
                })
                
        compact_candidates.append({
            "check_item_id": item.check_item_id,
            "title": item.title,
            "requirement_text": item.requirement_text,
            "acceptance_criteria": item.acceptance_criteria,
            "keyword_confidence": float(mapping.confidence if mapping else 0.0),
            "candidates": candidates,
        })
        
    if not evidence_catalog:
        return keyword_mappings

    try:
        agent = _get_agent(
            "evidence_mapper",
            name="Review-Plus 证据映射复核",
            output_schema=EvidenceMappingOutput,
            instructions=[
                "你是航天审查证据映射专家，负责从候选证据中选择最能支撑检查项的原文。",
                "只能返回输入候选中的 evidence_id；不要编造新的 evidence_id。",
                "如果候选无法支撑检查项，可返回空 evidence_ids 并说明原因。",
            ],
        )
        output = _run_agent_structured(
            agent,
            "请复核检查项到证据的映射，保留最直接、最可审计的证据。\n"
            f"items={json.dumps(compact_candidates, ensure_ascii=False)}",
            EvidenceMappingOutput,
        )
    except Exception as exc:
        logger.warning("[ReviewPlusAgent] evidence mapping failed: %s", exc)
        return None

    refined_by_id = {item.check_item_id: item for item in output.mappings}
    refined: list[ReviewPlusSectionMapping] = []
    for original in keyword_mappings:
        item = refined_by_id.get(original.check_item_id)
        valid_ids = [eid for eid in (item.evidence_ids if item else []) if eid in evidence_catalog]
        if not item:
            refined.append(original)
            continue
        entries = [evidence_catalog[eid] for eid in valid_ids]
        refined.append(ReviewPlusSectionMapping(
            check_item_id=original.check_item_id,
            section_ids=[entry["section_id"] for entry in entries],
            section_titles=[entry["section_title"] for entry in entries],
            evidence_ids=[entry["evidence_id"] for entry in entries],
            evidence_quotes=[entry["quote"] for entry in entries],
            confidence=max(0.0, min(float(item.confidence or 0.0), 1.0)),
            method="llm_evidence",
            rationale=item.rationale or "LLM 证据映射复核",
        ))
    return refined


def build_cross_document_items_with_agent(task: Any, deterministic_items: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
    materials = [
        {
            **_material_sample(material, max_chars=1800),
            "document_version": getattr(material, "document_version", ""),
            "baseline_id": getattr(material, "baseline_id", ""),
        }
        for material in getattr(task, "materials", [])[:10]
    ]
    try:
        agent = _get_agent(
            "cross_document_reviewer",
            name="Review-Plus 跨文档一致性审查",
            output_schema=CrossDocumentReviewOutput,
            instructions=[
                "你是航天多文档一致性审查专家，负责发现任务书、检查单、报告、附件之间的缺口和矛盾。",
                "重点检查指标口径、版本基线、任务书要求是否被报告印证、检查单要求是否被送审材料覆盖。",
                "每个问题必须有 source_quote 或明确材料依据；不要编造不存在的文档内容。",
            ],
        )
        output = _run_agent_structured(
            agent,
            "请在规则审查结果基础上补充跨文档一致性问题。\n"
            f"deterministic_items={json.dumps(deterministic_items[:80], ensure_ascii=False)}\n"
            f"traceability_summary={json.dumps((getattr(task, 'traceability_result', {}) or {}).get('summary', {}), ensure_ascii=False)}\n"
            f"materials={json.dumps(materials, ensure_ascii=False)}",
            CrossDocumentReviewOutput,
        )
    except Exception as exc:
        logger.warning("[ReviewPlusAgent] cross-document review failed: %s", exc)
        return None

    items: list[dict[str, Any]] = []
    for idx, raw in enumerate(output.items, start=1):
        if not raw.title and not raw.description:
            continue
        items.append({
            "review_item_id": f"rp-llm-cross-{idx}",
            "item_type": raw.item_type or "cross_document_issue",
            "severity": raw.severity or "major",
            "title": raw.title or "跨文档一致性问题",
            "description": raw.description,
            "impact": raw.impact or "跨文档不一致会削弱审查结论的可追溯性。",
            "recommendation": raw.recommendation or "补充明确引用关系、修订说明或支撑证据。",
            "source_artifact_ids": [],
            "target_artifact_ids": [],
            "evidence_ids": [],
            "source_quote": raw.source_quote,
            "status": "open",
            "method": "llm_cross_document",
        })
    return items


def compose_report_with_agent(task: Any, deterministic_report: ReviewPlusReport) -> ReviewPlusReport | None:
    try:
        agent = _get_agent(
            "report_composer",
            name="Review-Plus 合稿师",
            output_schema=ReportCompositionOutput,
            instructions=[
                "你是航天审查委员会合稿师，负责将检查项 findings 与跨文档问题归并为正式审查报告结论。",
                "必须基于输入统计和 findings，不要改变计数字段。",
                "conclusion 应给出明确放行/整改/补证建议，residual_risks 要覆盖证据不足和跨文档风险。",
            ],
        )
        compact_findings = [
            {
                "check_item_id": finding.check_item_id,
                "judgment": finding.judgment.value if hasattr(finding.judgment, "value") else str(finding.judgment),
                "severity": finding.severity.value if hasattr(finding.severity, "value") else str(finding.severity),
                "title": finding.title,
                "reasoning": finding.reasoning[:500],
                "recommendation": finding.recommendation[:300],
                "confidence": finding.confidence,
            }
            for finding in list(getattr(task, "findings", []) or [])[:120]
        ]
        output = _run_agent_structured(
            agent,
            "请基于 Review-Plus 审查结果生成合稿结论、摘要、残余风险和交叉引用。\n"
            f"deterministic_report={json.dumps(deterministic_report.model_dump(), ensure_ascii=False, default=str)}\n"
            f"findings={json.dumps(compact_findings, ensure_ascii=False)}\n"
            f"cross_document_items={json.dumps(list(getattr(task, 'cross_document_review_items', []) or [])[:80], ensure_ascii=False)}",
            ReportCompositionOutput,
        )
    except Exception as exc:
        logger.warning("[ReviewPlusAgent] report composition failed: %s", exc)
        return None

    report_data = deterministic_report.model_dump()
    if output.conclusion:
        report_data["conclusion"] = output.conclusion
    if output.summary:
        report_data["summary"] = output.summary
    if output.residual_risks:
        report_data["residual_risks"] = output.residual_risks
    if output.cross_references:
        report_data["cross_references"] = output.cross_references
    try:
        return ReviewPlusReport.model_validate(report_data)
    except Exception as exc:
        logger.warning("[ReviewPlusAgent] report validation failed: %s", exc)
        return None


__all__ = [
    "build_cross_document_items_with_agent",
    "compose_report_with_agent",
    "detect_scenario_with_agent",
    "extract_check_items_with_agent",
    "refine_mappings_with_agent",
]
