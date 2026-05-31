"""
单元审查执行服务 (Unit Review Service)

这是 GNC 评审的核心执行引擎，无论是 AD 还是 AC 的任何细分单元，
其审查动作（除合并、决策外的实际挑刺动作）都应该被规范化为以下固定步骤：
1. 定位章节 (Locate Sections)
2. 打包证据 (Build Evidence Bundle)
3. 执行规则模型推理 (Execute Unit Rules)
4. 抽取结果 (Extract Findings & Finalize Result)

本服务接收大模型 Agent 实例和上下文，返回统一的 UnitReviewResult。
如果 Gatekeeping 状态为 hard_fail，则执行器会直接熔断（断路），输出占位结果，不调用大模型。
"""

import logging
from typing import Any, Callable

from data_agent.parsing.schemas import DocumentSectionTree
from data_agent.review.p0_schemas import (
    UnitEvidenceBundle,
    UnitReviewResult,
    RuleExecutionResult,
    UnitFinding,
)
from data_agent.integrations.satellite_review.evidence_pool_service import (
    build_unit_primary_evidences,
    merge_supporting_evidences,
)
from data_agent.integrations.satellite_review.rule_execution_service import execute_quantitative_rules
from data_agent.integrations.satellite_review.template_gatekeeping_service import _match_sections_for_unit

logger = logging.getLogger(__name__)


def _normalize_finding_severity(value: Any) -> str:
    raw = str(value or "").strip().lower()
    mapping = {
        "high": "critical",
        "medium": "major",
        "low": "minor",
        "critical": "critical",
        "major": "major",
        "minor": "minor",
        "suggestion": "suggestion",
    }
    return mapping.get(raw, "minor")


def _expand_with_descendants(
    section_ids: list[str],
    section_tree: DocumentSectionTree,
) -> list[str]:
    """递归展开，将命中章节的全部子孙章节自动纳入。

    解决的问题: 父章节 "3、姿态确定算法设计" 命中 ad_algorithm，
    但子章节 "3.2、各敏感器之间系统误差修正" 因标题无关键词而被遗漏。
    纳入后，该子章节的证据也会被分配给对应 agent。
    """
    sections_by_id = {s.section_id: s for s in section_tree.sections}
    expanded = set(section_ids)

    def _recurse(sid: str):
        sec = sections_by_id.get(sid)
        if not sec:
            return
        for child_id in sec.children_ids:
            if child_id not in expanded:
                expanded.add(child_id)
                _recurse(child_id)

    for sid in list(section_ids):
        _recurse(sid)

    return sorted(expanded)


def locate_unit_sections(unit_spec: dict, section_tree: DocumentSectionTree) -> list[str]:
    """定位给定单元的主责章节 ID 列表。

    流程:
      1. 通过标题关键词匹配 (复用门禁服务)
      2. 递归展开，自动纳入所有子孙章节
    """
    sections = _match_sections_for_unit(unit_spec, section_tree)
    matched_ids = [sec.section_id for sec in sections]
    return _expand_with_descendants(matched_ids, section_tree)


def build_unit_evidence_bundle(
    unit_spec: dict,
    matched_section_ids: list[str],
    evidence_pool: Any,  # DocumentEvidencePool
    gatekeeping_status: str,
    warnings: list[str],
    extracted_parameters: list[dict[str, Any]] | None = None,
    extracted_objects: list[dict[str, Any]] | None = None,
    trace_link_candidates: list[dict[str, Any]] | None = None,
    trace_links: list[dict[str, Any]] | None = None,
) -> UnitEvidenceBundle:
    """提取该单元的主证据并打包。注意旁证将在 Agent 内部或后续检索流中添加。"""
    unit_key = unit_spec.get("unit_key", "unknown")
    primary_evs = build_unit_primary_evidences(
        unit_key=unit_key,
        matched_section_ids=matched_section_ids,
        evidence_pool=evidence_pool,
    )
    bundle = merge_supporting_evidences(
        unit_key=unit_key,
        primary_evidences=primary_evs,
        supporting_evidences=[],  # 初始为空，由 reviewer 侧补全或在 workflow 提供
        gatekeeping_status=gatekeeping_status,
        warnings=warnings,
    )
    bundle.extracted_parameters = list(extracted_parameters or [])
    bundle.extracted_objects = list(extracted_objects or [])
    bundle.trace_link_candidates = list(trace_link_candidates or [])
    bundle.trace_links = list(trace_links or [])
    return bundle


def get_unit_evidence_bundle(
    unit_key: str,
    unit_evidence_bundles: list[dict] | None,
) -> UnitEvidenceBundle | None:
    if not unit_evidence_bundles:
        return None
    for item in unit_evidence_bundles:
        if isinstance(item, dict) and item.get("unit_key") == unit_key:
            return UnitEvidenceBundle.model_validate(item)
    return None


def build_placeholder_result(
    unit_spec: dict,
    agent_id: str,
    reason: str,
) -> UnitReviewResult:
    """生成因前置关口未满足（如缺少主章节）而未开展深审的占位结果。"""
    return UnitReviewResult(
        unit_key=unit_spec.get("unit_key", "unknown"),
        unit_name=unit_spec.get("unit_name", ""),
        agent_id=agent_id,
        status="placeholder",
        summary=f"因前置条件未满足，本审查单元未开展深审。原因：{reason}",
        knowledge_gap=True,
        confidence=0.0,
    )


def execute_unit_rules(
    unit_spec: dict,
    agent_id: str,
    bundle: UnitEvidenceBundle,
    run_agent_func: Callable[[UnitEvidenceBundle, dict], Any],
) -> UnitReviewResult:
    """统包执行单元审查。
    
    Args:
        unit_spec: 模板中关于当前单元的设定
        agent_id: 负责运行的大模型的 agent_id
        bundle: 基于当前文档解析出的证据数据包
        run_agent_func: 具体投递到 LLM 的调用函数, 它接受 evidence bundle 和 unit specs
        
    Returns:
        标准的 UnitReviewResult。
    """
    unit_key = unit_spec.get("unit_key", "unknown")
    unit_name = unit_spec.get("unit_name", "")

    # 判断是否应当中止深审（hard_fail：必选章节缺失，不具备开展专业审查的输入条件）
    if bundle.gatekeeping_status == "hard_fail":
        logger.warning(f"[UnitReview] 单元 {unit_key} 门禁 hard_fail，未开展深审。")
        return build_placeholder_result(
            unit_spec=unit_spec,
            agent_id=agent_id,
            reason="该单元对应主章节在文档中缺失，模板门禁判定为不具备开展专业深审的输入条件。"
        )

    deterministic_results = execute_quantitative_rules(unit_spec, bundle)
    enriched_unit_spec = dict(unit_spec)
    enriched_unit_spec["deterministic_rule_results"] = [
        item.model_dump() for item in deterministic_results
    ]

    # 正常调用 Agent 执行
    try:
        raw_output = run_agent_func(bundle, enriched_unit_spec)
        result = _extract_unit_findings(unit_key, unit_name, agent_id, raw_output)
        result.rule_results = _merge_rule_results(deterministic_results, result.rule_results)
        result.evidence_ids = sorted({
            *result.evidence_ids,
            *(evidence_ref for item in deterministic_results for evidence_ref in item.evidence_refs),
        })
        if any(item.execution_status == "insufficient_evidence" for item in deterministic_results):
            result.knowledge_gap = True
        return result
    except Exception as e:
        logger.exception(f"[UnitReview] 审查执行发生系统异常 ({unit_key}): {e}")
        return UnitReviewResult(
            unit_key=unit_key,
            unit_name=unit_name,
            agent_id=agent_id,
            status="error",
            summary=f"审查执行过程遭遇异常: {str(e)}",
            rule_results=deterministic_results,
            knowledge_gap=True,
        )


def _extract_unit_findings(
    unit_key: str,
    unit_name: str,
    agent_id: str,
    raw_output: Any,
) -> UnitReviewResult:
    """将 LLM 输出转换为标准的 UnitReviewResult"""
    
    # 抽取 rule_results
    rule_results = []
    if hasattr(raw_output, "rule_results") and getattr(raw_output, "rule_results", None):
        rule_results = raw_output.rule_results
    elif hasattr(raw_output, "rule_judgments") and getattr(raw_output, "rule_judgments", None):
        # 向下兼容: 若输出仍是旧版本 RuleJudgment
        for r in raw_output.rule_judgments:
            rule_results.append(RuleExecutionResult(
                rule_id=r.rule_id if hasattr(r, "rule_id") else "UNKNOWN",
                passed=r.judgment == "satisfied" if hasattr(r, "judgment") else False,
                reasoning=r.rationale if hasattr(r, "rationale") else "",
                evidence_refs=r.evidence_ids if hasattr(r, "evidence_ids") else [],
                claim_present=getattr(r, "claim_present", None),
                claim_sufficient=getattr(r, "claim_sufficient", None),
                rule_consistent=getattr(r, "rule_consistent", None),
                support_status=getattr(r, "support_status", "") or "",
                residual_uncertainty=getattr(r, "residual_uncertainty", "") or "",
                execution_status="llm_checked",
            ))

    evidence_ids: set[str] = set()

    # 抽取 findings
    findings = []
    if hasattr(raw_output, "findings"):
        for f in raw_output.findings:
            evidence_refs = f.evidence_ids if hasattr(f, "evidence_ids") else []
            evidence_ids.update(evidence_refs)
            findings.append(UnitFinding(
                unit_key=unit_key,
                description=f.reasoning_path if hasattr(f, "reasoning_path") else getattr(f, "description", ""),
                severity=_normalize_finding_severity(
                    f.risk_level if hasattr(f, "risk_level") else "minor"
                ),
                evidence_refs=evidence_refs,
                recommendation=f.recommendation if hasattr(f, "recommendation") else "",
            ))

    status = "completed"
    if hasattr(raw_output, "completed") and not getattr(raw_output, "completed"):
        status = "incomplete"

    summary = getattr(raw_output, "summary", "审查执行完毕。")
    confidence = float(getattr(raw_output, "confidence", 0.0) or 0.0)
    for item in rule_results:
        evidence_ids.update(item.evidence_refs)
    is_blocked = any(getattr(f, "blocking_flag", False) for f in getattr(raw_output, "findings", []) or [])

    return UnitReviewResult(
        unit_key=unit_key,
        unit_name=unit_name,
        agent_id=agent_id,
        status=status,
        rule_results=rule_results,
        findings=findings,
        summary=summary,
        evidence_ids=sorted(evidence_ids),
        is_blocked=is_blocked,
        knowledge_gap=bool(getattr(raw_output, "knowledge_gap", False)),
        confidence=confidence,
    )


def _merge_rule_results(
    deterministic_results: list[RuleExecutionResult],
    llm_results: list[RuleExecutionResult],
) -> list[RuleExecutionResult]:
    """Merge deterministic quantitative results with LLM results.

    Deterministic results win for the same rule_id because their pass/fail is
    based on the calculator. LLM-only results are preserved for qualitative
    checks and contextual findings.
    """
    merged: dict[str, RuleExecutionResult] = {}
    order: list[str] = []
    for item in llm_results or []:
        if item.rule_id not in merged:
            order.append(item.rule_id)
        merged[item.rule_id] = item
    for item in deterministic_results or []:
        if item.rule_id not in merged:
            order.insert(0, item.rule_id)
        merged[item.rule_id] = item
    return [merged[rule_id] for rule_id in order if rule_id in merged]
