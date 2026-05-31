"""Chief comprehensive review for Review-Plus file-group packages.

Synthesizes document corpus, evidence pool, specialist findings, traceability,
and draft report into a small set of senior-engineer-style conclusions.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Literal

from pydantic import BaseModel, Field

from data_agent.review_plus.schemas import (
    ReviewPlusChiefComprehensiveReview,
    ReviewPlusChiefEngineeringConclusion,
    ReviewPlusReport,
)

logger = logging.getLogger(__name__)

_SEVERITY_RANK = {"critical": 4, "major": 3, "minor": 2, "info": 1}


class ChiefEngineeringConclusionItem(BaseModel):
    title: str = ""
    description: str = ""
    evidence_sources: list[str] = Field(default_factory=list)
    involved_documents: list[str] = Field(default_factory=list)
    risk_impact: str = ""
    recommendation: str = ""
    severity: Literal["critical", "major", "minor", "info"] = "major"
    confidence: float = 0.0


class ChiefComprehensiveReviewOutput(BaseModel):
    overall_assessment: str = ""
    release_recommendation: Literal[
        "approve", "conditional", "reject", "needs_human_review"
    ] = "needs_human_review"
    engineering_conclusions: list[ChiefEngineeringConclusionItem] = Field(default_factory=list)
    key_risks: list[str] = Field(default_factory=list)
    rationale: str = ""


def _value(value: Any) -> str:
    return value.value if hasattr(value, "value") else str(value or "")


def _material_catalog(task: Any) -> list[dict[str, Any]]:
    from data_agent.review_plus.agent_service import _material_sample

    return [
        {
            **_material_sample(material, max_chars=1200),
            "document_version": getattr(material, "document_version", ""),
            "baseline_id": getattr(material, "baseline_id", ""),
        }
        for material in (getattr(task, "materials", []) or [])[:12]
    ]


def _section_outline(task: Any, *, limit: int = 24) -> list[dict[str, str]]:
    sections = (getattr(task, "section_tree", {}) or {}).get("sections") or []
    outline: list[dict[str, str]] = []
    for section in sections[:limit]:
        if not isinstance(section, dict):
            continue
        outline.append(
            {
                "section_id": str(section.get("section_id") or ""),
                "title": str(section.get("title") or "")[:120],
                "level": str(section.get("level") or ""),
            }
        )
    return outline


def _evidence_samples(task: Any, *, limit: int = 20) -> list[dict[str, str]]:
    evidences = (getattr(task, "evidence_pool", {}) or {}).get("evidences") or []
    samples: list[dict[str, str]] = []
    for evidence in evidences[:limit]:
        if not isinstance(evidence, dict):
            continue
        samples.append(
            {
                "evidence_id": str(evidence.get("evidence_id") or ""),
                "section_title": str(evidence.get("section_title") or evidence.get("title") or "")[:80],
                "quote": str(evidence.get("quote") or evidence.get("text") or "")[:240],
            }
        )
    return samples


def _compact_findings(task: Any, *, limit: int = 40) -> list[dict[str, Any]]:
    findings = list(getattr(task, "findings", []) or [])
    ranked = sorted(
        findings,
        key=lambda finding: (
            _SEVERITY_RANK.get(_value(getattr(finding, "severity", "")).lower(), 0),
            0 if _value(getattr(finding, "judgment", "")) == "not_satisfied" else 1,
            -float(getattr(finding, "confidence", 0.0) or 0.0),
        ),
        reverse=True,
    )
    compact: list[dict[str, Any]] = []
    for finding in ranked[:limit]:
        compact.append(
            {
                "finding_id": getattr(finding, "finding_id", ""),
                "check_item_id": getattr(finding, "check_item_id", ""),
                "judgment": _value(getattr(finding, "judgment", "")),
                "severity": _value(getattr(finding, "severity", "")),
                "title": getattr(finding, "title", ""),
                "reasoning": (getattr(finding, "reasoning", "") or "")[:400],
                "recommendation": (getattr(finding, "recommendation", "") or "")[:240],
                "confidence": float(getattr(finding, "confidence", 0.0) or 0.0),
                "source_quotes": (getattr(finding, "source_quotes", []) or [])[:2],
            }
        )
    return compact


def _compact_specialist_reviews(task: Any, *, limit: int = 8) -> list[dict[str, Any]]:
    reviews: list[dict[str, Any]] = []
    for review in (getattr(task, "specialist_reviews", []) or [])[:limit]:
        if not isinstance(review, dict):
            continue
        findings = review.get("findings") or []
        reviews.append(
            {
                "agent_id": review.get("agent_id", ""),
                "agent_name": review.get("agent_name", ""),
                "status": review.get("status", ""),
                "finding_count": review.get("finding_count", len(findings)),
                "findings": [
                    {
                        "title": item.get("title", ""),
                        "description": (item.get("description") or item.get("reasoning") or "")[:240],
                        "severity": item.get("severity", ""),
                        "recommendation": (item.get("recommendation") or "")[:180],
                    }
                    for item in findings[:5]
                    if isinstance(item, dict)
                ],
            }
        )
    return reviews


def _build_review_context(task: Any, draft_report: ReviewPlusReport) -> dict[str, Any]:
    return {
        "review_plus_id": getattr(task, "review_plus_id", ""),
        "scenario": getattr(task, "scenario", ""),
        "materials": _material_catalog(task),
        "section_outline": _section_outline(task),
        "evidence_samples": _evidence_samples(task),
        "traceability_summary": (getattr(task, "traceability_result", {}) or {}).get("summary", {}),
        "cross_document_items": list(getattr(task, "cross_document_review_items", []) or [])[:20],
        "findings": _compact_findings(task),
        "specialist_reviews": _compact_specialist_reviews(task),
        "draft_report": {
            "conclusion": draft_report.conclusion,
            "summary": draft_report.summary,
            "total_check_items": draft_report.total_check_items,
            "not_satisfied_count": draft_report.not_satisfied_count,
            "insufficient_evidence_count": draft_report.insufficient_evidence_count,
            "critical_count": draft_report.critical_count,
            "residual_risks": draft_report.residual_risks[:8],
        },
        "chief_review_plan_summary": {
            "selected_agents": [
                {
                    "agent_id": item.get("agent_id", ""),
                    "agent_name": item.get("agent_name", ""),
                }
                for item in ((getattr(task, "chief_review_plan", {}) or {}).get("selected_agents") or [])[:12]
                if isinstance(item, dict)
            ],
            "focus_questions": ((getattr(task, "chief_review_plan", {}) or {}).get("focus_questions") or [])[:6],
        },
    }


def _finding_to_conclusion(
    *,
    title: str,
    description: str,
    recommendation: str,
    severity: str,
    confidence: float,
    evidence_sources: list[str] | None = None,
    involved_documents: list[str] | None = None,
    risk_impact: str = "",
) -> ReviewPlusChiefEngineeringConclusion:
    return ReviewPlusChiefEngineeringConclusion(
        title=title or "工程审查问题",
        description=description,
        evidence_sources=evidence_sources or [],
        involved_documents=involved_documents or [],
        risk_impact=risk_impact or "可能影响审查结论的可追溯性与放行判断。",
        recommendation=recommendation or "请补充证据或修订相关文档后复核。",
        severity=severity or "major",
        confidence=max(0.0, min(float(confidence or 0.0), 1.0)),
    )


def _fallback_chief_comprehensive_review(
    task: Any,
    draft_report: ReviewPlusReport,
    *,
    reason: str = "",
) -> ReviewPlusChiefComprehensiveReview:
    """Heuristic synthesis when LLM chief review is unavailable."""
    conclusions: list[ReviewPlusChiefEngineeringConclusion] = []
    seen_titles: set[str] = set()

    def _append(conclusion: ReviewPlusChiefEngineeringConclusion) -> None:
        key = conclusion.title.strip().lower()
        if not key or key in seen_titles:
            return
        seen_titles.add(key)
        conclusions.append(conclusion)

    findings = list(getattr(task, "findings", []) or [])
    for finding in sorted(
        findings,
        key=lambda item: (
            _SEVERITY_RANK.get(_value(getattr(item, "severity", "")).lower(), 0),
            0 if _value(getattr(item, "judgment", "")) == "not_satisfied" else 1,
        ),
        reverse=True,
    ):
        judgment = _value(getattr(finding, "judgment", ""))
        if judgment not in {"not_satisfied", "insufficient_evidence"}:
            continue
        title = getattr(finding, "title", "") or "检查项问题"
        reasoning = getattr(finding, "reasoning", "") or ""
        if judgment == "insufficient_evidence" and "证据不足" in reasoning and len(reasoning) < 40:
            reasoning = f"检查项「{title}」缺少可审计支撑证据，无法形成满足判定。"
        _append(
            _finding_to_conclusion(
                title=title,
                description=reasoning,
                recommendation=getattr(finding, "recommendation", "") or "补充任务书/报告/检查单支撑证据。",
                severity=_value(getattr(finding, "severity", "")) or "major",
                confidence=float(getattr(finding, "confidence", 0.0) or 0.0),
                evidence_sources=list(getattr(finding, "source_quotes", []) or [])[:2],
                involved_documents=[
                    name
                    for name in [
                        getattr(finding, "checklist_source_material_name", ""),
                    ]
                    if name
                ],
                risk_impact=(
                    "不满足项会直接影响符合性判定。"
                    if judgment == "not_satisfied"
                    else "证据不足会导致审查结论不可审计，存在漏判风险。"
                ),
            )
        )
        if len(conclusions) >= 6:
            break

    for item in (getattr(task, "cross_document_review_items", []) or [])[:4]:
        if not isinstance(item, dict):
            continue
        _append(
            _finding_to_conclusion(
                title=str(item.get("title") or "跨文档一致性问题"),
                description=str(item.get("description") or item.get("impact") or ""),
                recommendation=str(item.get("recommendation") or "补充跨文档引用关系或统一口径。"),
                severity=str(item.get("severity") or "major"),
                confidence=0.75,
                evidence_sources=[str(item.get("source_quote") or "")] if item.get("source_quote") else [],
                involved_documents=[],
                risk_impact=str(item.get("impact") or "跨文档不一致会削弱审查闭环。"),
            )
        )

    for review in (getattr(task, "specialist_reviews", []) or [])[:4]:
        if not isinstance(review, dict):
            continue
        for finding in (review.get("findings") or [])[:2]:
            if not isinstance(finding, dict):
                continue
            severity = str(finding.get("severity") or "major")
            if severity not in {"critical", "major"}:
                continue
            _append(
                _finding_to_conclusion(
                    title=str(finding.get("title") or review.get("agent_name") or "专家审查问题"),
                    description=str(finding.get("description") or finding.get("reasoning") or ""),
                    recommendation=str(finding.get("recommendation") or "请按专家意见补充或修订。"),
                    severity=severity,
                    confidence=0.7,
                    evidence_sources=[],
                    involved_documents=[str(review.get("agent_name") or review.get("agent_id") or "")],
                    risk_impact="专家审查识别出的结构性或一致性问题需优先闭环。",
                )
            )
            if len(conclusions) >= 8:
                break

    key_risks = list(draft_report.residual_risks or [])[:6]
    if not key_risks and conclusions:
        key_risks = [item.risk_impact for item in conclusions[:4] if item.risk_impact]

    if draft_report.critical_count or any(item.severity == "critical" for item in conclusions):
        release = "reject"
    elif draft_report.not_satisfied_count or conclusions:
        release = "conditional"
    elif draft_report.insufficient_evidence_count:
        release = "needs_human_review"
    else:
        release = "approve"

    overall = draft_report.conclusion
    if reason:
        overall = (
            f"{overall} "
            f"（总审查员 LLM 综合判断不可用：{reason}，已降级为规则/专家摘要。）"
        ).strip()

    return ReviewPlusChiefComprehensiveReview(
        status="degraded" if reason else "ok",
        method="heuristic_fallback",
        overall_assessment=overall,
        release_recommendation=release,
        engineering_conclusions=conclusions[:8],
        key_risks=key_risks,
        rationale=(
            f"基于 {len(findings)} 条逐项 findings、"
            f"{len(getattr(task, 'cross_document_review_items', []) or [])} 条跨文档问题、"
            f"{len(getattr(task, 'specialist_reviews', []) or [])} 组专家审查结果进行启发式综合。"
        ),
        degraded=bool(reason),
        degrade_reason=reason,
    )


def _run_llm_chief_review(task: Any, draft_report: ReviewPlusReport) -> ReviewPlusChiefComprehensiveReview | None:
    from data_agent.review_plus.agent_service import _agents_enabled, _get_agent, _run_agent_structured

    if not _agents_enabled():
        return None

    context = _build_review_context(task, draft_report)
    try:
        agent = _get_agent(
            "chief_comprehensive_reviewer",
            name="Review-Plus 总审查员",
            output_schema=ChiefComprehensiveReviewOutput,
            instructions=[
                "你是航天文件组审查的总审查员，具备资深工程审查经验。",
                "请基于材料正文摘要、证据池、专家 findings、追溯与跨文档结果，给出少量高价值工程结论。",
                "不要逐条重复所有检查项；应合并同类问题，突出放行风险与必须整改项。",
                "每条 engineering_conclusions 必须包含：问题标题、问题描述、证据来源、涉及文档、风险影响、建议、严重度、置信度。",
                "overall_assessment 应像资深审查员写给项目方的结论，避免“证据不足”模板化空话。",
                "release_recommendation 取值 approve/conditional/reject/needs_human_review。",
            ],
        )
        output = _run_agent_structured(
            agent,
            "请给出总审查员综合判断。\n"
            f"context={json.dumps(context, ensure_ascii=False)[:28000]}",
            ChiefComprehensiveReviewOutput,
        )
    except Exception as exc:
        logger.warning("[ReviewPlusChief] LLM chief comprehensive review failed: %s", exc)
        return None

    if not output.overall_assessment and not output.engineering_conclusions:
        return None

    conclusions = [
        ReviewPlusChiefEngineeringConclusion(
            title=item.title,
            description=item.description,
            evidence_sources=list(item.evidence_sources or [])[:6],
            involved_documents=list(item.involved_documents or [])[:6],
            risk_impact=item.risk_impact,
            recommendation=item.recommendation,
            severity=item.severity,
            confidence=max(0.0, min(float(item.confidence or 0.0), 1.0)),
        )
        for item in (output.engineering_conclusions or [])[:8]
        if item.title or item.description
    ]

    return ReviewPlusChiefComprehensiveReview(
        status="ok",
        method="llm_chief",
        overall_assessment=output.overall_assessment or draft_report.conclusion,
        release_recommendation=output.release_recommendation or "needs_human_review",
        engineering_conclusions=conclusions,
        key_risks=list(output.key_risks or draft_report.residual_risks or [])[:8],
        rationale=output.rationale or "总审查员基于全文、证据与专家意见形成综合判断。",
        degraded=False,
        degrade_reason="",
    )


def run_chief_comprehensive_review(
    task: Any,
    draft_report: ReviewPlusReport,
) -> ReviewPlusChiefComprehensiveReview:
    """Run chief comprehensive review with LLM first, heuristic fallback on failure."""
    llm_result = _run_llm_chief_review(task, draft_report)
    if llm_result and llm_result.engineering_conclusions:
        return llm_result
    if llm_result and llm_result.overall_assessment:
        return llm_result

    reason = "LLM 总审查员不可用或未产出结构化结论"
    if llm_result is None:
        from data_agent.review_plus.agent_service import _agents_enabled

        if not _agents_enabled():
            reason = "Review-Plus Agent 增强已关闭（REVIEW_PLUS_AGENTS_ENABLED=0）"

    return _fallback_chief_comprehensive_review(task, draft_report, reason=reason)


__all__ = [
    "run_chief_comprehensive_review",
    "ReviewPlusChiefComprehensiveReview",
]
