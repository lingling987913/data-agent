"""Harness-style multi-agent review orchestration for Review-Plus.

Required agent runtime failures are surfaced as workflow failures. Recoverable
data-quality issues, such as stale evidence aliases, are kept inside review
outputs so the workflow can still produce diagnosable artifacts.
"""

from __future__ import annotations

import re
import time
from collections import Counter
from typing import Any, Callable, Literal

from pydantic import BaseModel, Field, ValidationError

from data_agent.core.agent_debug_log import agent_debug_log

from data_agent.review_plus.schemas import (
    ReviewPlusFinding,
    ReviewPlusFindingSeverity,
    ReviewPlusJudgment,
    ReviewPlusMaterialRole,
)
from data_agent.review_plus.evidence_mapping_service import section_mapping_refs_by_role
from data_agent.review_plus.cross_document_utils import (
    formal_material_baseline_values,
    formal_material_version_values,
)
from data_agent.review_plus.package_slots import evaluate_review_plus_package_slots
from data_agent.review_plus.text_utils import (
    all_review_text,
    iter_material_lines,
    lexical_score,
    role_value,
)


CORE_AGENT_IDS = (
    "material_package_agent",
    "chief_orchestrator_agent",
    "coverage_matrix_builder_agent",
    "review_plus_arbiter_agent",
)

SPECIALIST_AGENT_IDS = (
    "checklist_agent",
    "task_book_agent",
    "subject_report_agent",
    "product_assurance_agent",
    "reliability_safety_agent",
    "gnc_design_agent",
    "interface_agent",
    "verification_agent",
    "cross_document_consistency_agent",
)

# Backward-compatible export name used by tests and callers that need the
# always-required control agents. Dynamic specialist membership is stored in
# ReviewPlusHarnessPlan.selected_agent_ids.
REQUIRED_AGENT_IDS = CORE_AGENT_IDS


# Maps specialist orchestration agent IDs to harness specialist IDs.
# Includes the 9 legacy reviewers plus the AD/AC professional review units so
# dynamically selected units route to a deterministic harness specialist.
SPECIALIST_TO_HARNESS_AGENT = {
    "product_assurance_reviewer": "product_assurance_agent",
    "reliability_safety_reviewer": "reliability_safety_agent",
    "gnc_design_reviewer": "gnc_design_agent",
    "attitude_control_reviewer": "gnc_design_agent",
    "attitude_determination_reviewer": "gnc_design_agent",
    "interface_reviewer": "interface_agent",
    "verification_reviewer": "verification_agent",
    "requirements_traceability_reviewer": "cross_document_consistency_agent",
    # AD 姿态确定专业组（7 单元）
    "ad_requirement_error_unit": "cross_document_consistency_agent",
    "ad_sampling_timing_unit": "gnc_design_agent",
    "ad_mounting_pointing_unit": "gnc_design_agent",
    "ad_determination_algorithm_unit": "gnc_design_agent",
    "ad_simulation_analysis_unit": "verification_agent",
    "ad_cross_consistency_unit": "cross_document_consistency_agent",
    "ad_report_completeness_unit": "product_assurance_agent",
    # AC 姿态控制专业组（10 单元）
    "ac_requirement_error_unit": "cross_document_consistency_agent",
    "ac_thruster_layout_unit": "gnc_design_agent",
    "ac_actuator_layout_unit": "gnc_design_agent",
    "ac_control_law_unit": "gnc_design_agent",
    "ac_control_param_unit": "gnc_design_agent",
    "ac_maneuver_control_unit": "gnc_design_agent",
    "ac_momentum_unload_unit": "gnc_design_agent",
    "ac_control_simulation_unit": "verification_agent",
    "ac_cross_consistency_unit": "cross_document_consistency_agent",
    "ac_report_completeness_unit": "product_assurance_agent",
}


class ReviewPlusAgentHarnessError(RuntimeError):
    """Raised when a required Review-Plus harness agent cannot complete."""

    def __init__(
        self,
        message: str,
        *,
        agent_id: str = "",
        error_code: str = "agent_failed",
        agent_run_traces: list["AgentRunTrace"] | None = None,
    ) -> None:
        super().__init__(message)
        self.agent_id = agent_id
        self.error_code = error_code
        self.agent_run_traces = agent_run_traces or []


class EvidenceRef(BaseModel):
    evidence_id: str = ""
    material_name: str = ""
    role: str = ""
    line_no: int = 0
    quote: str = ""


class TaskBookRequirement(BaseModel):
    requirement_id: str = ""
    title: str = ""
    requirement_text: str = ""
    evidence_id: str = ""
    source_quote: str = ""
    confidence: float = 0.0
    requires_human_confirmation: bool = False


class CoverageMatrixRow(BaseModel):
    check_item_id: str = ""
    check_item_title: str = ""
    checklist_source_role: str = ""
    checklist_source_material_name: str = ""
    task_book_evidence_refs: list[str] = Field(default_factory=list)
    subject_evidence_refs: list[str] = Field(default_factory=list)
    judgment: Literal["satisfied", "not_satisfied", "insufficient_evidence", "not_applicable", "not_checked"] = (
        "not_checked"
    )
    coverage_status: Literal["closed", "task_only", "subject_only", "missing"] = "missing"
    confidence: float = 0.0
    risks: list[str] = Field(default_factory=list)
    source_quote: str = ""
    requires_human_confirmation: bool = False


class ReviewPlusCoverageMatrix(BaseModel):
    rows: list[CoverageMatrixRow] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)


class AgentReviewIssue(BaseModel):
    issue_id: str = ""
    item_type: str = ""
    severity: Literal["critical", "major", "minor", "info"] = "major"
    title: str = ""
    description: str = ""
    recommendation: str = ""
    source_quote: str = ""
    source_evidence_ids: list[str] = Field(default_factory=list)
    method: str = ""
    confidence: float = 0.0
    requires_human_confirmation: bool = False


class AgentCoverageContribution(BaseModel):
    agent_id: str = ""
    check_item_id: str = ""
    task_book_evidence_refs: list[str] = Field(default_factory=list)
    subject_evidence_refs: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    requires_human_confirmation: bool = False


class AgentRunTrace(BaseModel):
    agent_id: str
    status: Literal["completed", "failed"]
    input_summary: dict[str, Any] = Field(default_factory=dict)
    output_summary: dict[str, Any] = Field(default_factory=dict)
    elapsed_ms: int = 0
    error_code: str = ""
    error_message: str = ""


class ReviewPlusHarnessPlan(BaseModel):
    team_id: str = "review_plus_dynamic_harness_team"
    selected_agent_ids: list[str] = Field(default_factory=list)
    required_agent_ids: list[str] = Field(default_factory=list)
    selection_reasons: dict[str, str] = Field(default_factory=dict)
    material_roles: list[str] = Field(default_factory=list)
    matched_signals: dict[str, list[str]] = Field(default_factory=dict)


class ReviewPlusHarnessOutput(BaseModel):
    coverage_matrix: ReviewPlusCoverageMatrix
    findings: list[ReviewPlusFinding] = Field(default_factory=list)
    cross_document_items: list[dict[str, Any]] = Field(default_factory=list)
    agent_run_traces: list[AgentRunTrace] = Field(default_factory=list)
    harness_plan: ReviewPlusHarnessPlan = Field(default_factory=ReviewPlusHarnessPlan)


def _iter_material_evidence(task: Any, roles: set[str]) -> list[EvidenceRef]:
    evidences: list[EvidenceRef] = []
    for line in iter_material_lines(task):
        if line["role"] not in roles:
            continue
        evidences.append(
            EvidenceRef(
                evidence_id=line["evidence_id"],
                material_name=line["material_name"],
                role=line["role"],
                line_no=int(line.get("line_no") or 0),
                quote=line["text"],
            )
        )
    return evidences


def _best_evidence_refs(query: str, evidences: list[EvidenceRef], *, threshold: float = 0.08, limit: int = 3) -> list[str]:
    scored = [(round(lexical_score(query, evidence.quote), 4), evidence) for evidence in evidences]
    scored = [(score, evidence) for score, evidence in scored if score >= threshold]
    scored.sort(key=lambda item: item[0], reverse=True)
    return [evidence.evidence_id for _, evidence in scored[:limit]]


def _require_non_empty(value: list[Any], *, agent_id: str, what: str) -> None:
    if not value:
        raise ReviewPlusAgentHarnessError(f"{agent_id} produced no {what}", agent_id=agent_id, error_code="empty_output")


def _build_evidence_catalog(
    task: Any,
    task_evidences: list[EvidenceRef],
    subject_evidences: list[EvidenceRef],
) -> dict[str, EvidenceRef]:
    """Merge line-based and structured document evidence IDs for arbiter validation."""
    from data_agent.review_plus.evidence_mapping_service import _collect_structured_evidence, _material_role_by_name

    catalog = {item.evidence_id: item for item in [*task_evidences, *subject_evidences]}
    roles_by_name = _material_role_by_name(task)
    for item in _collect_structured_evidence(task):
        evidence_id = str(item.get("evidence_id") or "")
        if not evidence_id or evidence_id in catalog:
            continue
        material_name = str(item.get("material_name") or "")
        catalog[evidence_id] = EvidenceRef(
            evidence_id=evidence_id,
            material_name=material_name,
            role=roles_by_name.get(material_name, ""),
            line_no=0,
            quote=str(item.get("text") or item.get("summary") or "")[:500],
        )
    return catalog


def _evidence_aliases(evidence_id: str, evidence: EvidenceRef) -> set[str]:
    aliases = {evidence_id}
    if evidence_id.startswith(("sec:", "ev:", "chunk:")):
        parts = evidence_id.split(":")
        aliases.update(part for part in parts[1:] if part)
    if evidence_id.startswith("sec:"):
        aliases.add(evidence_id.removeprefix("sec:"))
    if evidence_id.startswith("chunk:"):
        aliases.add(evidence_id.removeprefix("chunk:"))
    if evidence.material_name and evidence.line_no:
        aliases.add(f"{evidence.material_name}:line-{evidence.line_no}")
    return aliases


def _build_evidence_alias_index(evidence_catalog: dict[str, EvidenceRef]) -> dict[str, str]:
    alias_index: dict[str, str] = {}
    for evidence_id, evidence in evidence_catalog.items():
        for alias in _evidence_aliases(evidence_id, evidence):
            alias_index.setdefault(alias, evidence_id)
    return alias_index


def _resolve_evidence_ref(
    raw_ref: str,
    evidence_catalog: dict[str, EvidenceRef],
    alias_index: dict[str, str],
) -> str:
    ref = str(raw_ref or "").strip()
    if not ref:
        return ""
    if ref in evidence_catalog:
        return ref
    return alias_index.get(ref, "")


def _normalize_coverage_row_refs(
    rows: list[CoverageMatrixRow],
    evidence_catalog: dict[str, EvidenceRef],
) -> list[str]:
    """Normalize row evidence refs and downgrade stale refs to review risks.

    LLM/agent-assisted mapping can occasionally return a section or chunk alias
    instead of the canonical evidence_id. The arbiter contract is stricter: all
    refs that survive here must be resolvable in the catalog.
    """
    alias_index = _build_evidence_alias_index(evidence_catalog)
    missing_refs: list[str] = []

    def normalize(refs: list[str]) -> tuple[list[str], list[str]]:
        normalized: list[str] = []
        missing: list[str] = []
        for ref in refs:
            resolved = _resolve_evidence_ref(ref, evidence_catalog, alias_index)
            if resolved:
                if resolved not in normalized:
                    normalized.append(resolved)
            else:
                missing.append(str(ref))
        return normalized, missing

    for row in rows:
        task_refs, missing_task_refs = normalize(row.task_book_evidence_refs)
        subject_refs, missing_subject_refs = normalize(row.subject_evidence_refs)
        row.task_book_evidence_refs = task_refs
        row.subject_evidence_refs = subject_refs

        row_missing = [*missing_task_refs, *missing_subject_refs]
        if not row_missing:
            continue

        missing_refs.extend(row_missing)
        row.requires_human_confirmation = True
        risk = f"部分证据引用无法解析，已移除并保留人工确认: {', '.join(row_missing[:3])}"
        if risk not in row.risks:
            row.risks.append(risk)

        if not task_refs and not subject_refs:
            row.coverage_status = "missing"
            if row.judgment == "satisfied":
                row.judgment = "insufficient_evidence"
        elif not task_refs:
            row.coverage_status = "subject_only"
        elif not subject_refs:
            row.coverage_status = "task_only"

    return sorted(set(missing_refs))


class ReviewPlusAgentHarness:
    """Strict multi-agent review harness used by the Review-Plus workflow."""

    def run(self, task: Any) -> ReviewPlusHarnessOutput:
        traces: list[AgentRunTrace] = []
        context: dict[str, Any] = {"task": task}
        self._run_agent("material_package_agent", self._material_package_agent, context, traces)
        self._run_agent("chief_orchestrator_agent", self._chief_orchestrator_agent, context, traces)
        plan: ReviewPlusHarnessPlan = context["harness_plan"]
        for agent_id in plan.selected_agent_ids:
            if agent_id == "cross_document_consistency_agent":
                continue
            self._run_agent(agent_id, self._specialist_runner(agent_id), context, traces)
        self._run_agent("coverage_matrix_builder_agent", self._coverage_matrix_builder_agent, context, traces)
        if "cross_document_consistency_agent" in plan.selected_agent_ids:
            self._run_agent(
                "cross_document_consistency_agent",
                self._cross_document_consistency_agent,
                context,
                traces,
            )
        self._run_agent("review_plus_arbiter_agent", self._review_plus_arbiter_agent, context, traces)

        output = ReviewPlusHarnessOutput(
            coverage_matrix=context["coverage_matrix"],
            findings=context["findings"],
            cross_document_items=context["cross_document_items"],
            agent_run_traces=traces,
            harness_plan=context["harness_plan"],
        )
        return output

    def _run_agent(
        self,
        agent_id: str,
        runner: Callable[[dict[str, Any]], dict[str, Any]],
        context: dict[str, Any],
        traces: list[AgentRunTrace],
    ) -> None:
        started = time.perf_counter()
        previous_agent_id = context.get("_current_agent_id")
        context["_current_agent_id"] = agent_id
        try:
            result = runner(context)
            context.update(result)
            traces.append(
                AgentRunTrace(
                    agent_id=agent_id,
                    status="completed",
                    input_summary=self._input_summary(agent_id, context),
                    output_summary=self._output_summary(result),
                    elapsed_ms=int((time.perf_counter() - started) * 1000),
                )
            )
        except ReviewPlusAgentHarnessError as exc:
            traces.append(
                AgentRunTrace(
                    agent_id=agent_id,
                    status="failed",
                    input_summary=self._input_summary(agent_id, context),
                    elapsed_ms=int((time.perf_counter() - started) * 1000),
                    error_code=exc.error_code,
                    error_message=str(exc),
                )
            )
            exc.agent_run_traces = list(traces)
            raise
        except (ValidationError, Exception) as exc:
            traces.append(
                AgentRunTrace(
                    agent_id=agent_id,
                    status="failed",
                    input_summary=self._input_summary(agent_id, context),
                    elapsed_ms=int((time.perf_counter() - started) * 1000),
                    error_code="schema_or_runtime_error",
                    error_message=str(exc),
                )
            )
            wrapped = ReviewPlusAgentHarnessError(
                str(exc),
                agent_id=agent_id,
                error_code="schema_or_runtime_error",
                agent_run_traces=list(traces),
            )
            raise wrapped from exc
        finally:
            if previous_agent_id is None:
                context.pop("_current_agent_id", None)
            else:
                context["_current_agent_id"] = previous_agent_id

    def _material_package_agent(self, context: dict[str, Any]) -> dict[str, Any]:
        task = context["task"]
        blocking, missing_slots, limited, role_set = evaluate_review_plus_package_slots(task)
        smart_bootstrap = bool(getattr(task, "smart_bootstrap_mode", False))
        if blocking and smart_bootstrap:
            warnings = list(context.get("smart_bootstrap_warnings") or [])
            warnings.extend(f"smart_bootstrap_slot_gap:{item}" for item in blocking)
            context["smart_bootstrap_warnings"] = warnings
            blocking = []
        if blocking:
            code = "missing_rule_source"
            if "任务书" in blocking[0]:
                code = "missing_task_book"
            elif "被审报告" in blocking[0]:
                code = "missing_subject"
            raise ReviewPlusAgentHarnessError(
                blocking[0],
                agent_id="material_package_agent",
                error_code=code,
            )
        result: dict[str, Any] = {"material_roles": sorted(role for role in role_set if role)}
        if smart_bootstrap and (missing_slots or limited):
            result["smart_bootstrap_warnings"] = [
                *(missing_slots or []),
                *(limited or []),
            ]
        return result

    def _chief_orchestrator_agent(self, context: dict[str, Any]) -> dict[str, Any]:
        task = context["task"]
        material_roles = list(context.get("material_roles") or [])
        all_text = all_review_text(task)
        selected: list[str] = []
        reasons: dict[str, str] = {}
        matched: dict[str, list[str]] = {}

        def select(agent_id: str, reason: str, signals: list[str] | None = None) -> None:
            if agent_id in selected:
                return
            selected.append(agent_id)
            reasons[agent_id] = reason
            matched[agent_id] = signals or []

        chief_plan = getattr(task, "chief_review_plan", None) or {}
        for specialist in chief_plan.get("selected_agents") or []:
            specialist_id = str(specialist.get("agent_id") or "")
            harness_id = SPECIALIST_TO_HARNESS_AGENT.get(specialist_id)
            if harness_id:
                select(
                    harness_id,
                    str(specialist.get("reason") or f"总师编排已选择 {specialist_id}。"),
                    list(specialist.get("matched_signals") or []),
                )

        select("checklist_agent", "材料包包含检查单/审查规则，必须抽取并复核检查项。")
        select("task_book_agent", "材料包包含任务书，必须抽取任务书要求。")
        select("subject_report_agent", "材料包包含被审报告/待审文档，必须抽取报告证据。")
        if "product_assurance_agent" not in selected:
            select("product_assurance_agent", "检查单/审查规则属于产品保证审查入口。")

        trigger_map = {
            "reliability_safety_agent": ["可靠性", "安全性", "故障", "失效", "FMEA", "FTA", "风险", "单点"],
            "gnc_design_agent": ["GNC", "姿态", "轨道", "导航", "控制", "飞轮", "星敏", "陀螺"],
            "interface_agent": ["接口", "ICD", "输入", "输出", "供电", "通信", "机械", "边界"],
            "verification_agent": ["验证", "仿真", "试验", "测试", "工况", "覆盖", "验收"],
        }
        lowered = all_text.lower()
        for agent_id, triggers in trigger_map.items():
            if agent_id in selected:
                continue
            hits = [trigger for trigger in triggers if trigger.lower() in lowered]
            if hits:
                select(agent_id, f"总师根据材料内容识别到专业信号: {', '.join(hits[:6])}。", hits)

        if len(getattr(task, "materials", []) or []) >= 2 and "cross_document_consistency_agent" not in selected:
            select("cross_document_consistency_agent", "多材料包必须检查跨文档版本、基线与证据闭合一致性。")

        plan = ReviewPlusHarnessPlan(
            selected_agent_ids=selected,
            required_agent_ids=[*CORE_AGENT_IDS, *selected],
            selection_reasons=reasons,
            material_roles=material_roles,
            matched_signals=matched,
        )
        _require_non_empty(plan.selected_agent_ids, agent_id="chief_orchestrator_agent", what="selected_agents")
        return {"harness_plan": plan}

    def _specialist_runner(self, agent_id: str) -> Callable[[dict[str, Any]], dict[str, Any]]:
        mapping: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
            "checklist_agent": self._checklist_agent,
            "task_book_agent": self._task_book_agent,
            "subject_report_agent": self._subject_report_agent,
            "product_assurance_agent": self._domain_specialist_agent,
            "reliability_safety_agent": self._domain_specialist_agent,
            "gnc_design_agent": self._domain_specialist_agent,
            "interface_agent": self._domain_specialist_agent,
            "verification_agent": self._domain_specialist_agent,
            "cross_document_consistency_agent": self._cross_document_consistency_agent,
        }
        if agent_id not in mapping:
            raise ReviewPlusAgentHarnessError(f"unknown specialist agent: {agent_id}", agent_id=agent_id, error_code="unknown_agent")
        return mapping[agent_id]

    def _checklist_agent(self, context: dict[str, Any]) -> dict[str, Any]:
        task = context["task"]
        check_items = list(getattr(task, "check_items", []) or [])
        _require_non_empty(check_items, agent_id="checklist_agent", what="check_items")
        role_by_name = {getattr(material, "name", ""): role_value(material) for material in getattr(task, "materials", []) or []}
        for item in check_items:
            if not getattr(item, "source_role", ""):
                item.source_role = role_by_name.get(getattr(item, "source_material_name", ""), "")
            if not getattr(item, "source_quote", ""):
                item.source_quote = getattr(item, "requirement_text", "") or getattr(item, "title", "")
        return {"check_items": check_items}

    def _task_book_agent(self, context: dict[str, Any]) -> dict[str, Any]:
        task = context["task"]
        task_evidences = _iter_material_evidence(task, {ReviewPlusMaterialRole.TASK_BOOK.value})
        _require_non_empty(task_evidences, agent_id="task_book_agent", what="task_book_evidence")
        requirements: list[TaskBookRequirement] = []
        for index, evidence in enumerate(task_evidences, start=1):
            if not re.search(r"应|要求|验收|交付|指标|覆盖|验证|符合|shall|must", evidence.quote, re.IGNORECASE):
                continue
            requirements.append(
                TaskBookRequirement(
                    requirement_id=f"TB-REQ-{index:03d}",
                    title=evidence.quote[:60],
                    requirement_text=evidence.quote,
                    evidence_id=evidence.evidence_id,
                    source_quote=evidence.quote,
                    confidence=0.72,
                    requires_human_confirmation=False,
                )
            )
        _require_non_empty(requirements, agent_id="task_book_agent", what="task_book_requirements")
        return {"task_evidences": task_evidences, "task_book_requirements": requirements}

    def _subject_report_agent(self, context: dict[str, Any]) -> dict[str, Any]:
        task = context["task"]
        subject_evidences = _iter_material_evidence(
            task,
            {
                ReviewPlusMaterialRole.SUBJECT_REPORT.value,
                ReviewPlusMaterialRole.SUBJECT_DOCUMENT.value,
                ReviewPlusMaterialRole.SUPPORTING_ATTACHMENT.value,
            },
        )
        _require_non_empty(subject_evidences, agent_id="subject_report_agent", what="subject_evidence")
        return {"subject_evidences": subject_evidences}

    def _domain_specialist_agent(self, context: dict[str, Any]) -> dict[str, Any]:
        plan: ReviewPlusHarnessPlan = context["harness_plan"]
        agent_id = self._current_agent_from_plan_context(context)
        check_items = context.get("check_items") or []
        task_evidences = context.get("task_evidences") or []
        subject_evidences = context.get("subject_evidences") or []
        signals = plan.matched_signals.get(agent_id, [])
        contributions = list(context.get("coverage_contributions") or [])
        signal_text = " ".join(signals)
        for item in check_items:
            item_text = " ".join([
                getattr(item, "title", "") or "",
                getattr(item, "requirement_text", "") or "",
                signal_text,
            ]).strip()
            if signals and not any(signal.lower() in item_text.lower() for signal in signals):
                continue
            task_refs = _best_evidence_refs(item_text, task_evidences, threshold=0.05, limit=2)
            subject_refs = _best_evidence_refs(item_text, subject_evidences, threshold=0.05, limit=2)
            if not task_refs and not subject_refs:
                continue

            # SymPy / Numpy 数值公式预计与降额设计复核 (Reliability Calculator Tool)
            calc_risks = []
            if agent_id == "reliability_safety_agent":
                item_desc = (getattr(item, "title", "") or "") + " " + (getattr(item, "requirement_text", "") or "")
                if any(kw in item_desc for kw in ["预计", "分配", "建模", "可靠度", "公式"]):
                    # 尝试从候选证据中提取可靠性数值
                    all_text_to_scan = " ".join([getattr(ev, "quote", "") for ev in task_evidences + subject_evidences])
                    numbers = [float(num) for num in re.findall(r"0\.\d{3,6}", all_text_to_scan)]
                    if len(numbers) >= 2:
                        try:
                            import numpy as np
                            import sympy as sp
                            series_val = float(np.prod(numbers))
                            parallel_val = float(1.0 - np.prod(1.0 - np.array(numbers)))
                            
                            R = sp.symbols('R')
                            formula = R**len(numbers)  # 对称串联模型
                            formula_diff = sp.diff(formula, R)
                            
                            calc_risks.append(
                                f"【SymPy/Numpy 预计复核】组件可靠度清单为 {numbers}。符号公式：R_sys = R^{len(numbers)}，导数 d(R_sys)/dR = {formula_diff}。代数预计：串联可靠度预计值 = {series_val:.5f}；并联冗余可靠度预计值 = {parallel_val:.5f}。"
                            )
                        except Exception as calc_exc:
                            logger.warning("[ReliabilityCalculator] sympy/numpy calculation failed: %s", calc_exc)

            risks_list = [] if task_refs and subject_refs else [f"{agent_id} 未找到完整的任务书到报告闭环证据。"]
            if calc_risks:
                risks_list.extend(calc_risks)

            contributions.append(
                AgentCoverageContribution(
                    agent_id=agent_id,
                    check_item_id=getattr(item, "check_item_id", ""),
                    task_book_evidence_refs=task_refs,
                    subject_evidence_refs=subject_refs,
                    risks=risks_list,
                    confidence=0.62 if task_refs and subject_refs else 0.38,
                    requires_human_confirmation=not (task_refs and subject_refs),
                )
            )
        return {
            "coverage_contributions": contributions,
            "domain_contributions": {
                **(context.get("domain_contributions") or {}),
                agent_id: {
                    "signals": signals,
                    "contribution_count": sum(1 for item in contributions if item.agent_id == agent_id),
                    "status": "completed",
                },
            },
        }

    def _current_agent_from_plan_context(self, context: dict[str, Any]) -> str:
        # _run_agent stores the current id before invoking dynamic specialists.
        return str(context.get("_current_agent_id") or "")

    def _coverage_matrix_builder_agent(self, context: dict[str, Any]) -> dict[str, Any]:
        task = context["task"]
        check_items = context["check_items"]
        task_evidences = context["task_evidences"]
        subject_evidences = context["subject_evidences"]
        contributions_by_item: dict[str, list[AgentCoverageContribution]] = {}
        for contribution in context.get("coverage_contributions") or []:
            contributions_by_item.setdefault(contribution.check_item_id, []).append(contribution)
        has_section_mappings = bool(getattr(task, "section_mappings", None))
        rows: list[CoverageMatrixRow] = []
        for item in check_items:
            query = " ".join(
                [
                    getattr(item, "title", "") or "",
                    getattr(item, "requirement_text", "") or "",
                    getattr(item, "acceptance_criteria", "") or "",
                    getattr(item, "applicable_scope", "") or "",
                ]
            ).strip()
            check_item_id = getattr(item, "check_item_id", "")
            if has_section_mappings:
                task_refs, subject_refs = section_mapping_refs_by_role(task, check_item_id)
            else:
                task_refs, subject_refs = [], []
            if not task_refs:
                task_refs = _best_evidence_refs(query, task_evidences)
            if not subject_refs:
                subject_refs = _best_evidence_refs(query, subject_evidences)
            contribution_refs = contributions_by_item.get(getattr(item, "check_item_id", ""), [])
            for contribution in contribution_refs:
                task_refs.extend(ref for ref in contribution.task_book_evidence_refs if ref not in task_refs)
                subject_refs.extend(ref for ref in contribution.subject_evidence_refs if ref not in subject_refs)
            if task_refs and subject_refs:
                judgment = "satisfied"
                status = "closed"
                confidence = max([0.76, *(contribution.confidence for contribution in contribution_refs)] or [0.76])
                risks: list[str] = [
                    risk
                    for contribution in contribution_refs
                    for risk in contribution.risks
                    if risk
                ]
            elif task_refs:
                judgment = "insufficient_evidence"
                status = "task_only"
                confidence = max([0.46, *(contribution.confidence for contribution in contribution_refs)] or [0.46])
                risks = [
                    "检查项在任务书中有依据，但被审报告/待审文档缺少直接印证。",
                    *[
                        risk
                        for contribution in contribution_refs
                        for risk in contribution.risks
                        if risk
                    ],
                ]
            elif subject_refs:
                judgment = "insufficient_evidence"
                status = "subject_only"
                confidence = max([0.42, *(contribution.confidence for contribution in contribution_refs)] or [0.42])
                risks = [
                    "检查项在被审报告/待审文档中有相近证据，但任务书依据不足。",
                    *[
                        risk
                        for contribution in contribution_refs
                        for risk in contribution.risks
                        if risk
                    ],
                ]
            else:
                judgment = "insufficient_evidence"
                status = "missing"
                confidence = 0.25
                risks = ["检查项未找到可审计的任务书依据或报告印证。"]
            rows.append(
                CoverageMatrixRow(
                    check_item_id=getattr(item, "check_item_id", ""),
                    check_item_title=getattr(item, "title", "") or getattr(item, "requirement_text", "")[:60],
                    checklist_source_role=getattr(item, "source_role", ""),
                    checklist_source_material_name=getattr(item, "source_material_name", ""),
                    task_book_evidence_refs=task_refs,
                    subject_evidence_refs=subject_refs,
                    judgment=judgment,
                    coverage_status=status,
                    confidence=confidence,
                    risks=risks,
                    source_quote=getattr(item, "source_quote", ""),
                    requires_human_confirmation=status != "closed"
                    or any(contribution.requires_human_confirmation for contribution in contribution_refs),
                )
            )
        _require_non_empty(rows, agent_id="coverage_matrix_builder_agent", what="coverage_rows")
        evidence_catalog = _build_evidence_catalog(task, task_evidences, subject_evidences)
        unresolved_refs = _normalize_coverage_row_refs(rows, evidence_catalog)
        missing_refs = sorted(
            ref
            for row in rows
            for ref in [*row.task_book_evidence_refs, *row.subject_evidence_refs]
            if ref not in evidence_catalog
        )
        agent_debug_log(
            "review_plus_agent_harness.py:_coverage_matrix_builder_agent",
            "evidence catalog built",
            {
                "catalog_size": len(evidence_catalog),
                "row_count": len(rows),
                "missing_ref_count": len(missing_refs),
                "missing_refs_sample": missing_refs[:5],
                "unresolved_ref_count": len(unresolved_refs),
                "unresolved_refs_sample": unresolved_refs[:5],
            },
            hypothesis_id="D",
            run_id="schema-fix",
        )
        return {
            "coverage_rows": rows,
            "evidence_catalog": evidence_catalog,
            "unresolved_evidence_refs": unresolved_refs,
        }

    def _cross_document_consistency_agent(self, context: dict[str, Any]) -> dict[str, Any]:
        rows: list[CoverageMatrixRow] = context["coverage_rows"]
        task = context["task"]
        issues: list[AgentReviewIssue] = []
        for row in rows:
            if row.coverage_status == "closed":
                continue
            issues.append(
                AgentReviewIssue(
                    issue_id=f"agent-coverage-{len(issues) + 1}",
                    item_type="check_item_coverage_gap",
                    severity="major",
                    title="检查单条款未形成任务书到报告的闭环证据",
                    description=f"检查项 {row.check_item_title or row.check_item_id} 覆盖状态为 {row.coverage_status}。",
                    recommendation="补充任务书依据、报告章节印证或人工确认不适用。",
                    source_quote=row.source_quote,
                    source_evidence_ids=[*row.task_book_evidence_refs, *row.subject_evidence_refs],
                    method="agent_consistency",
                    confidence=max(row.confidence, 0.35),
                    requires_human_confirmation=True,
                )
            )

        version_values = formal_material_version_values(task)
        baseline_values = formal_material_baseline_values(task)
        if len(version_values) > 1:
            issues.append(
                AgentReviewIssue(
                    issue_id=f"agent-version-{len(issues) + 1}",
                    item_type="baseline_version_mismatch",
                    severity="major",
                    title="多文档版本标识不一致",
                    description=f"正式材料存在多个版本号: {', '.join(sorted(version_values))}。",
                    recommendation="统一版本引用或补充版本差异说明。",
                    method="agent_consistency",
                    confidence=0.9,
                    requires_human_confirmation=False,
                )
            )
        if len(baseline_values) > 1:
            issues.append(
                AgentReviewIssue(
                    issue_id=f"agent-baseline-{len(issues) + 1}",
                    item_type="baseline_version_mismatch",
                    severity="major",
                    title="多文档基线标识不一致",
                    description=f"正式材料存在多个基线标识: {', '.join(sorted(baseline_values))}。",
                    recommendation="统一基线引用或补充基线差异说明。",
                    method="agent_consistency",
                    confidence=0.9,
                    requires_human_confirmation=False,
                )
            )
        return {"agent_issues": issues}

    def _review_plus_arbiter_agent(self, context: dict[str, Any]) -> dict[str, Any]:
        rows: list[CoverageMatrixRow] = context["coverage_rows"]
        issues: list[AgentReviewIssue] = context.get("agent_issues") or []
        evidence_catalog: dict[str, EvidenceRef] = context["evidence_catalog"]
        unresolved_refs = list(context.get("unresolved_evidence_refs") or [])
        missing_refs = _normalize_coverage_row_refs(rows, evidence_catalog)
        unresolved_refs = sorted(set([*unresolved_refs, *missing_refs]))
        if unresolved_refs:
            issues.append(
                AgentReviewIssue(
                    issue_id="agent-evidence-ref-recovered",
                    item_type="evidence_reference_recovered",
                    severity="major",
                    title="部分证据引用未能定位到送审包证据库",
                    description=(
                        "覆盖矩阵中存在已失效或非规范化的证据引用，系统已移除无效引用并将相关检查项标记为待确认。"
                    ),
                    recommendation="复核证据映射结果；必要时重新执行证据映射或补充材料章节引用。",
                    method="evidence_ref_normalization",
                    confidence=0.9,
                    requires_human_confirmation=True,
                )
            )
        status_counts = Counter(row.coverage_status for row in rows)
        matrix = ReviewPlusCoverageMatrix(
            rows=rows,
            summary={
                "row_count": len(rows),
                "closed_count": status_counts.get("closed", 0),
                "task_only_count": status_counts.get("task_only", 0),
                "subject_only_count": status_counts.get("subject_only", 0),
                "missing_count": status_counts.get("missing", 0),
                "unresolved_evidence_ref_count": len(unresolved_refs),
                "unresolved_evidence_refs": unresolved_refs[:20],
                "ruleset_version": "review-plus-v2-agent-harness-2026-05-20",
            },
        )
        findings = [self._finding_from_row(row) for row in rows]
        cross_items = [self._issue_to_review_item(issue, idx) for idx, issue in enumerate(self._dedupe_issues(issues), start=1)]
        return {"coverage_matrix": matrix, "findings": findings, "cross_document_items": cross_items}

    def _finding_from_row(self, row: CoverageMatrixRow) -> ReviewPlusFinding:
        severity = (
            ReviewPlusFindingSeverity.INFO
            if row.judgment == "satisfied"
            else ReviewPlusFindingSeverity.MAJOR
            if row.coverage_status in {"missing", "task_only"}
            else ReviewPlusFindingSeverity.MINOR
        )
        reasoning = (
            "检查项已同时找到任务书依据和被审报告/待审文档印证。"
            if row.coverage_status == "closed"
            else "；".join(row.risks) or "检查项证据链未闭合。"
        )
        
        calc_risks = [r for r in row.risks if "SymPy/Numpy" in r]
        if calc_risks:
            reasoning = reasoning + " " + "；".join(calc_risks)

        recommendation = "" if row.coverage_status == "closed" else "补充任务书依据、报告章节印证或人工确认该检查项不适用。"
        return ReviewPlusFinding(
            check_item_id=row.check_item_id,
            judgment=ReviewPlusJudgment(row.judgment),
            severity=severity,
            title=row.check_item_title or "检查项覆盖审查",
            reasoning=reasoning,
            evidence_refs=[*row.task_book_evidence_refs, *row.subject_evidence_refs],
            task_book_evidence_refs=list(row.task_book_evidence_refs),
            subject_evidence_refs=list(row.subject_evidence_refs),
            source_quotes=[row.source_quote] if row.source_quote else [],
            recommendation=recommendation,
            confidence=row.confidence,
            source_quote=row.source_quote,
            checklist_source_role=row.checklist_source_role,
            checklist_source_material_name=row.checklist_source_material_name,
            coverage_status=row.coverage_status,
        )

    def _issue_to_review_item(self, issue: AgentReviewIssue, index: int) -> dict[str, Any]:
        return {
            "review_item_id": f"rp-agent-cross-{index}",
            "item_type": issue.item_type,
            "severity": issue.severity,
            "title": issue.title,
            "description": issue.description,
            "impact": "多文档证据链不闭合会削弱审查结论的可追溯性和可验收性。",
            "recommendation": issue.recommendation,
            "source_artifact_ids": [],
            "target_artifact_ids": [],
            "evidence_ids": list(issue.source_evidence_ids),
            "source_quote": issue.source_quote,
            "status": "open",
            "method": issue.method or "agent_arbiter",
            "confidence": issue.confidence,
            "requires_human_confirmation": issue.requires_human_confirmation,
        }

    def _dedupe_issues(self, issues: list[AgentReviewIssue]) -> list[AgentReviewIssue]:
        seen: set[tuple[str, str, str]] = set()
        deduped: list[AgentReviewIssue] = []
        for issue in issues:
            key = (issue.item_type, issue.title, issue.description)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(issue)
        return deduped

    def _input_summary(self, agent_id: str, context: dict[str, Any]) -> dict[str, Any]:
        task = context.get("task")
        return {
            "agent_id": agent_id,
            "material_count": len(getattr(task, "materials", []) or []) if task else 0,
            "check_item_count": len(context.get("check_items") or getattr(task, "check_items", []) or []) if task else 0,
            "coverage_row_count": len(context.get("coverage_rows") or []),
        }

    def _output_summary(self, result: dict[str, Any]) -> dict[str, Any]:
        summary: dict[str, Any] = {}
        for key, value in result.items():
            if isinstance(value, list):
                summary[f"{key}_count"] = len(value)
            elif isinstance(value, dict):
                summary[f"{key}_count"] = len(value)
            elif isinstance(value, BaseModel):
                summary[key] = value.__class__.__name__
            else:
                summary[key] = str(value)[:120]
        return summary


__all__ = [
            "AgentReviewIssue",
    "AgentCoverageContribution",
    "AgentRunTrace",
    "CORE_AGENT_IDS",
    "CoverageMatrixRow",
    "REQUIRED_AGENT_IDS",
    "ReviewPlusAgentHarness",
    "ReviewPlusAgentHarnessError",
    "ReviewPlusCoverageMatrix",
    "ReviewPlusHarnessPlan",
    "SPECIALIST_AGENT_IDS",
]
