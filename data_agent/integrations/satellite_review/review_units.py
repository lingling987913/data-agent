"""AD/AC professional review-unit utilities shared by GNC / Review-Plus / SMART.

The 17 AD/AC review units are defined once in the domain registry
(``config/domains/aerospace_review.json``). This module provides the three
capabilities the orchestration routes need on top of that single source:

- ``select_units_by_signals``  : material-signal-driven dynamic unit selection.
- ``build_unit_template_gatekeeping`` : per-unit template section gatekeeping.
- ``run_unit_review``          : execute a unit review (LLM when available,
  deterministic degraded finding otherwise, always with trace metadata).
"""

from __future__ import annotations

import logging
import os
from typing import Any

from data_agent.core.domain_registry import review_units_for_domain
from data_agent.integrations.satellite_review.review_template_service import (
    _get_stage_section_keywords,
    build_unit_specs,
    resolve_template,
)
from data_agent.integrations.satellite_review.template_gatekeeping_service import (
    run_template_gatekeeping,
)
from data_agent.integrations.satellite_review.unit_review_service import (
    build_unit_evidence_bundle,
    execute_unit_rules,
    get_unit_evidence_bundle,
    locate_unit_sections,
)
from data_agent.integrations.satellite_review.rule_execution_service import (
    format_rule_execution_prompt_section,
)
from data_agent.parsing.schemas import (
    DocumentEvidencePool,
    DocumentSection,
    DocumentSectionTree,
    TemplateGatekeepingResult,
)
from data_agent.review.p0_schemas import RuleExecutionResult, UnitEvidenceBundle, UnitFinding, UnitReviewResult

logger = logging.getLogger(__name__)

# 与 JSON 模板路径及 run_template_gatekeeping 默认 min_text_length=200 对齐，
# 避免注册表回退与 resolve_template/build_unit_specs 路径判定不一致。
_REGISTRY_MIN_TEXT_LENGTH = 200

# aq-aero 等上游常只传 {"template_id": "GNC_ALL"} stub，不含 required_sections。
_TEMPLATE_STUB_KEYS = frozenset({"template_id", "id", "name"})


def _extract_template_id(template: dict | None, fallback: str = "") -> str:
    if isinstance(template, dict):
        nested = str(template.get("template_id") or template.get("id") or "").strip()
        if nested:
            return nested
    return str(fallback or "").strip()


def _is_template_stub(template: dict) -> bool:
    if not template:
        return False
    keys = {str(key) for key in template.keys()}
    if keys and keys.issubset(_TEMPLATE_STUB_KEYS):
        return True
    if _extract_template_id(template) and not build_unit_specs(template):
        return True
    return False


def _resolve_gatekeeping_template(
    template: dict | None,
    *,
    template_id: str = "",
    subsystem: str = "GNC",
    review_phase: str = "CDR",
) -> dict | None:
    """将 stub 或缺失模板解析为完整 JSON 模板；完整模板原样返回。"""
    effective_template_id = _extract_template_id(template, template_id)
    if template is not None and not _is_template_stub(template):
        return template
    if effective_template_id:
        resolved = resolve_template(subsystem, review_phase, template_id=effective_template_id)
        if resolved:
            return resolved
    return None

# registry unit_id -> (ad|ac prefix, template stage_key)
_REGISTRY_UNIT_STAGE: dict[str, tuple[str, str]] = {
    "ad_requirement_error_unit": ("ad", "req_err"),
    "ad_sampling_timing_unit": ("ad", "timing"),
    "ad_mounting_pointing_unit": ("ad", "install"),
    "ad_determination_algorithm_unit": ("ad", "algorithm"),
    "ad_simulation_analysis_unit": ("ad", "simulation"),
    "ac_requirement_error_unit": ("ac", "req_err"),
    "ac_thruster_layout_unit": ("ac", "thruster_layout"),
    "ac_actuator_layout_unit": ("ac", "other_actuator_layout"),
    "ac_control_law_unit": ("ac", "control_law"),
    "ac_control_param_unit": ("ac", "control_params"),
    "ac_maneuver_control_unit": ("ac", "maneuver_law"),
    "ac_momentum_unload_unit": ("ac", "unloading_law"),
    "ac_control_simulation_unit": ("ac", "simulation"),
}


def _unit_triggers(unit_payload: dict[str, Any]) -> list[str]:
    return [str(trigger) for trigger in (unit_payload.get("triggers") or []) if str(trigger) != "all"]


def select_units_by_signals(
    text: str,
    *,
    domain_id: str = "aerospace_review",
    group: str | None = None,
    max_units: int | None = None,
) -> list[dict[str, Any]]:
    """Dynamically select AD/AC review units whose triggers hit the material text.

    Returns a list of ``{unit_id, unit_name, unit_group, unit_order, role,
    matched_signals}`` ordered by unit group/order. Only units with at least one
    matched trigger are returned (signal-driven, "命中才上场").
    """
    units = review_units_for_domain(domain_id, group=group)
    lowered = (text or "").lower()
    selected: list[dict[str, Any]] = []
    for unit_id, payload in units.items():
        hits = [trigger for trigger in _unit_triggers(payload) if trigger.lower() in lowered]
        if not hits:
            continue
        selected.append(
            {
                "unit_id": unit_id,
                "unit_name": str(payload.get("name") or unit_id),
                "unit_group": str(payload.get("unit_group") or ""),
                "unit_order": int(payload.get("unit_order") or 0),
                "role": str(payload.get("role") or ""),
                "matched_signals": hits,
            }
        )
    if max_units is not None and max_units >= 0:
        selected = selected[:max_units]
    return selected


def _unit_canonical_title(unit_name: str) -> str:
    """从注册表单元名称提取期望主章节标题（如 AC-控制律设计审查单元 -> 控制律设计）。"""
    core = unit_name
    if "-" in core:
        core = core.split("-", 1)[1]
    for suffix in ("审查单元", "设计审查单元"):
        if core.endswith(suffix):
            core = core[: -len(suffix)]
    return core.strip()


def _registry_unit_spec(unit_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """无 JSON 模板时，从领域注册表组装与源服务兼容的 UnitSpec。"""
    unit_name = str(payload.get("name") or unit_id)
    template_sections = [str(item) for item in (payload.get("template_sections") or []) if str(item)]
    prefix_stage = _REGISTRY_UNIT_STAGE.get(unit_id)
    stage_keywords: list[str] = []
    if prefix_stage:
        prefix, stage_key = prefix_stage
        stage_keywords = list(_get_stage_section_keywords(prefix).get(stage_key, []))

    alias_titles = list(dict.fromkeys(stage_keywords + template_sections[1:]))
    keyword_backfill = list(dict.fromkeys(stage_keywords + template_sections))
    required_titles: list[str] = []
    canonical = _unit_canonical_title(unit_name)
    if canonical:
        required_titles.append(canonical)

    return {
        "unit_key": unit_id,
        "unit_name": unit_name,
        "required_titles": required_titles,
        "alias_titles": alias_titles,
        "keyword_backfill": keyword_backfill,
        "subsection_titles": [],
        "min_text_length": _REGISTRY_MIN_TEXT_LENGTH,
    }


def _index_template_unit_specs(template: dict, review_scope: str) -> dict[str, dict]:
    """template unit_key (ac_control_law) 与 registry unit_id (ac_control_law_unit) 双向索引。"""
    indexed: dict[str, dict] = {}
    for spec in build_unit_specs(template, review_scope=review_scope):
        unit_key = str(spec.get("unit_key") or "")
        if not unit_key:
            continue
        indexed[unit_key] = spec
        registry_id = unit_key if unit_key.endswith("_unit") else f"{unit_key}_unit"
        indexed[registry_id] = spec
    return indexed


def _unit_specs_for_gatekeeping(
    units: list[dict[str, Any]],
    catalog: dict[str, dict[str, Any]],
    *,
    template: dict | None = None,
    review_scope: str = "ad_ac",
) -> list[dict]:
    template_index = _index_template_unit_specs(template, review_scope) if template else {}
    specs: list[dict] = []
    for unit in units:
        unit_id = str(unit.get("unit_id") or "")
        payload = catalog.get(unit_id, {})
        unit_name = str(unit.get("unit_name") or payload.get("name") or unit_id)
        if not (payload.get("template_sections") or template_index.get(unit_id)):
            continue

        if unit_id in template_index:
            spec = dict(template_index[unit_id])
        else:
            spec = _registry_unit_spec(unit_id, payload)
        spec["unit_key"] = unit_id
        spec["unit_name"] = unit_name
        specs.append(spec)
    return specs


def _flatten_raw_sections(section_tree: Any) -> list[dict[str, Any]]:
    raw_sections: list[dict[str, Any]] = []
    if not isinstance(section_tree, dict):
        return raw_sections
    direct = section_tree.get("sections")
    if isinstance(direct, list):
        for section in direct:
            if isinstance(section, dict):
                raw_sections.append(section)
    for document in section_tree.get("documents") or []:
        if not isinstance(document, dict):
            continue
        document_name = str(document.get("name") or "")
        for section in document.get("sections") or []:
            if not isinstance(section, dict):
                continue
            merged = dict(section)
            merged.setdefault("source_file_name", document_name)
            raw_sections.append(merged)
    return raw_sections


def _coerce_document_section_tree(
    section_tree: Any,
    evidences: list[dict[str, Any]] | None = None,
) -> DocumentSectionTree:
    """将 GNC 工作流 dict 章节树 + 证据池规范为 DocumentSectionTree（供源门控服务使用）。"""
    sections_by_id: dict[str, DocumentSection] = {}
    for index, raw in enumerate(_flatten_raw_sections(section_tree)):
        section_id = str(raw.get("section_id") or f"sec-{index}")
        sections_by_id[section_id] = DocumentSection(
            section_id=section_id,
            title=str(raw.get("title") or ""),
            level=int(raw.get("level") or 1),
            number=str(raw.get("number") or ""),
            parent_section_id=raw.get("parent_section_id"),
            start_block_index=int(raw.get("start_block_index") or index),
            end_block_index=int(raw.get("end_block_index") or index + 1),
            text=str(raw.get("text") or ""),
            source_file_name=str(raw.get("source_file_name") or ""),
            children_ids=[str(child) for child in (raw.get("children_ids") or []) if child],
        )

    def _merge_quote_into_section(section_id: str, quote: str) -> None:
        if not quote or section_id not in sections_by_id:
            return
        section = sections_by_id[section_id]
        merged_text = "\n".join(part for part in (section.text, quote) if part)
        sections_by_id[section_id] = section.model_copy(update={"text": merged_text})

    def _find_section_id_by_title(title: str) -> str:
        for sid, section in sections_by_id.items():
            section_title = section.title.strip()
            if not section_title or not title:
                continue
            if title == section_title or title in section_title or section_title in title:
                return sid
        return ""

    for ev_index, evidence in enumerate(evidences or []):
        if not isinstance(evidence, dict):
            continue
        quote = str(
            evidence.get("quote")
            or evidence.get("excerpt")
            or evidence.get("summary")
            or ""
        ).strip()
        title = str(evidence.get("title") or "").strip()
        section_id = str(evidence.get("section_id") or "")
        if section_id and section_id in sections_by_id:
            _merge_quote_into_section(section_id, quote)
            continue
        if title:
            matched_id = _find_section_id_by_title(title)
            if matched_id:
                _merge_quote_into_section(matched_id, quote)
                continue
        if not quote and not title:
            continue
        evidence_id = str(evidence.get("evidence_id") or f"evidence-{ev_index}")
        sections_by_id[evidence_id] = DocumentSection(
            section_id=evidence_id,
            title=title or evidence_id,
            level=1,
            start_block_index=ev_index,
            end_block_index=ev_index + 1,
            text=quote,
            source_file_name=str(evidence.get("document_name") or evidence.get("source_file_name") or ""),
        )

    return DocumentSectionTree(sections=list(sections_by_id.values()))


def build_unit_template_gatekeeping(
    section_tree: Any,
    evidences: list[dict[str, Any]] | None = None,
    *,
    domain_id: str = "aerospace_review",
    units: list[dict[str, Any]] | None = None,
    template: dict | None = None,
    template_id: str = "",
    subsystem: str = "GNC",
    review_phase: str = "CDR",
    review_scope: str = "ad_ac",
) -> list[TemplateGatekeepingResult]:
    """按单元执行模板结构准入（委托源等价 ``run_template_gatekeeping``）。

    保留本函数名与 ``TemplateGatekeepingResult`` 输出以兼容 GNC Step 3 / 测试。
    当提供评审 JSON 模板时优先使用 ``required_titles`` / ``alias_titles`` /
    ``keyword_backfill`` / ``subsection_titles``；否则从领域注册表推导 UnitSpec。
    """
    catalog = review_units_for_domain(domain_id)
    if units is None:
        units = [
            {
                "unit_id": unit_id,
                "unit_name": str(payload.get("name") or unit_id),
                "unit_group": payload.get("unit_group"),
            }
            for unit_id, payload in catalog.items()
        ]

    resolved_template = _resolve_gatekeeping_template(
        template,
        template_id=template_id,
        subsystem=subsystem,
        review_phase=review_phase,
    )

    unit_specs = _unit_specs_for_gatekeeping(
        units,
        catalog,
        template=resolved_template,
        review_scope=review_scope,
    )

    results: list[TemplateGatekeepingResult] = []
    spec_unit_ids = {spec["unit_key"] for spec in unit_specs}
    for unit in units:
        unit_id = str(unit.get("unit_id") or "")
        payload = catalog.get(unit_id, {})
        unit_name = str(unit.get("unit_name") or payload.get("name") or unit_id)
        if unit_id not in spec_unit_ids:
            results.append(
                TemplateGatekeepingResult(
                    unit_key=unit_id,
                    unit_name=unit_name,
                    status="pass",
                    summary="该单元未定义模板章节，跳过模板门控。",
                )
            )

    if not unit_specs:
        return results

    tree = _coerce_document_section_tree(section_tree, evidences)
    gated = run_template_gatekeeping(tree, unit_specs)
    results.extend(gated)
    return results


def _evidence_subset_for_unit(
    unit_payload: dict[str, Any],
    evidences: list[dict[str, Any]],
    *,
    limit: int = 8,
) -> list[dict[str, Any]]:
    triggers = [trigger.lower() for trigger in _unit_triggers(unit_payload)]
    scored: list[tuple[int, dict[str, Any]]] = []
    for evidence in evidences or []:
        if not isinstance(evidence, dict):
            continue
        blob = f"{evidence.get('title', '')}\n{evidence.get('quote', '')}".lower()
        score = sum(1 for trigger in triggers if trigger and trigger in blob)
        if score:
            scored.append((score, evidence))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    subset = [evidence for _, evidence in scored[:limit]]
    if not subset:
        subset = [evidence for evidence in (evidences or []) if isinstance(evidence, dict)][:limit]
    return subset


def _llm_enabled() -> bool:
    return os.getenv("GNC_REVIEW_UNITS_LLM_ENABLED", "1").strip().lower() not in {"0", "false", "no"}


def _index_gatekeeping_results(quality_data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for item in quality_data.get("template_gatekeeping") or []:
        if isinstance(item, dict) and item.get("unit_key"):
            indexed[str(item["unit_key"])] = item
    return indexed


def _resolve_unit_spec_for_review(
    unit_id: str,
    unit_name: str,
    quality_data: dict[str, Any],
    catalog: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    intake = quality_data.get("intake_data") or {}
    gate_ctx = {
        "template": None,
        "template_id": "",
        "review_phase": str(intake.get("review_phase") or "CDR"),
        "review_scope": str(intake.get("review_scope") or "ad_ac"),
    }
    metadata = intake.get("metadata") if isinstance(intake.get("metadata"), dict) else {}
    for source in (intake.get("template"), metadata.get("template"), metadata.get("review_template")):
        if isinstance(source, dict) and source:
            gate_ctx["template"] = source
            break
    for candidate in (
        metadata.get("template_id"),
        metadata.get("review_template_id"),
        (gate_ctx["template"] or {}).get("template_id") if isinstance(gate_ctx["template"], dict) else "",
        (gate_ctx["template"] or {}).get("id") if isinstance(gate_ctx["template"], dict) else "",
    ):
        tid = str(candidate or "").strip()
        if tid:
            gate_ctx["template_id"] = tid
            break

    resolved_template = _resolve_gatekeeping_template(
        gate_ctx["template"],  # type: ignore[arg-type]
        template_id=gate_ctx["template_id"],
        subsystem="GNC",
        review_phase=gate_ctx["review_phase"],
    )
    if resolved_template:
        indexed = _index_template_unit_specs(resolved_template, review_scope=gate_ctx["review_scope"])
        if unit_id in indexed:
            spec = dict(indexed[unit_id])
            spec["unit_key"] = unit_id
            spec["unit_name"] = unit_name
            return spec

    payload = catalog.get(unit_id, {})
    spec = _registry_unit_spec(unit_id, payload)
    spec["unit_key"] = unit_id
    spec["unit_name"] = unit_name
    return spec


def _coerce_evidence_pool(raw_pool: Any, evidence_map: dict[str, dict[str, Any]]) -> DocumentEvidencePool:
    if isinstance(raw_pool, dict) and raw_pool.get("evidences"):
        return DocumentEvidencePool.model_validate(raw_pool)
    if isinstance(raw_pool, list):
        evidences = []
        for evidence in raw_pool:
            if not isinstance(evidence, dict) and hasattr(evidence, "model_dump"):
                evidence = evidence.model_dump(mode="json")
            if not isinstance(evidence, dict):
                continue
            evidences.append(
                {
                    "evidence_id": evidence.get("evidence_id", ""),
                    "section_id": evidence.get("section_id", ""),
                    "source_type": evidence.get("source_type") or "paragraph_excerpt",
                    "source_file_name": evidence.get("document_name") or evidence.get("source_file_name") or "",
                    "excerpt": evidence.get("quote") or evidence.get("excerpt") or "",
                    "summary": evidence.get("title") or evidence.get("summary") or "",
                    "matched_keywords": list(evidence.get("matched_keywords") or []),
                    "block_ids": list(evidence.get("block_ids") or []),
                }
            )
        return DocumentEvidencePool(evidences=evidences)
    evidences = []
    for evidence in evidence_map.values():
        if not isinstance(evidence, dict):
            continue
        evidences.append(
            {
                "evidence_id": evidence.get("evidence_id", ""),
                "section_id": evidence.get("section_id", ""),
                "source_type": evidence.get("source_type") or "paragraph_excerpt",
                "source_file_name": evidence.get("document_name") or evidence.get("source_file_name") or "",
                "excerpt": evidence.get("quote") or evidence.get("excerpt") or "",
                "summary": evidence.get("title") or "",
            }
        )
    return DocumentEvidencePool(evidences=evidences)


def build_unit_evidence_bundles_for_workflow(
    *,
    quality_data: dict[str, Any],
    section_tree: Any,
    evidence_pool: Any,
    extracted_parameters: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """为 GNC workflow 装配各审查单元的 evidence bundle（源 execute_unit_rules 输入）。"""
    intake = quality_data.get("intake_data") or {}
    gatekeeping_map = _index_gatekeeping_results(quality_data)
    review_scope = str(intake.get("review_scope") or "ad_ac")
    metadata = intake.get("metadata") if isinstance(intake.get("metadata"), dict) else {}
    template = None
    template_id = ""
    for source in (intake.get("template"), metadata.get("template"), metadata.get("review_template")):
        if isinstance(source, dict) and source:
            template = source
            break
    for candidate in (
        metadata.get("template_id"),
        metadata.get("review_template_id"),
        (template or {}).get("template_id") if isinstance(template, dict) else "",
        (template or {}).get("id") if isinstance(template, dict) else "",
    ):
        tid = str(candidate or "").strip()
        if tid:
            template_id = tid
            break

    resolved_template = _resolve_gatekeeping_template(
        template,
        template_id=template_id,
        subsystem="GNC",
        review_phase=str(intake.get("review_phase") or "CDR"),
    )
    if not resolved_template:
        return []

    tree = _coerce_document_section_tree(section_tree, None)
    pool = _coerce_evidence_pool(evidence_pool, {})
    unit_specs = build_unit_specs(resolved_template, review_scope=review_scope)
    bundles: list[dict] = []
    params = list(extracted_parameters or [])

    for spec in unit_specs:
        unit_key = str(spec.get("unit_key") or "")
        if not unit_key:
            continue
        registry_id = unit_key if unit_key.endswith("_unit") else f"{unit_key}_unit"
        gk = gatekeeping_map.get(registry_id) or gatekeeping_map.get(unit_key) or {}
        matched_ids = locate_unit_sections(spec, tree)
        bundle = build_unit_evidence_bundle(
            unit_spec={**spec, "unit_key": registry_id},
            matched_section_ids=matched_ids,
            evidence_pool=pool,
            gatekeeping_status=str(gk.get("status") or "pass"),
            warnings=[str(item) for item in (gk.get("issues") or []) if item],
            extracted_parameters=params,
        )
        bundle.unit_key = registry_id
        bundles.append(bundle.model_dump(mode="json"))
    return bundles


def _resolve_unit_evidence_bundle(
    unit_id: str,
    unit_spec: dict[str, Any],
    data: dict[str, Any],
    evidence_map: dict[str, dict[str, Any]],
    gatekeeping_map: dict[str, dict[str, Any]],
) -> UnitEvidenceBundle:
    prebuilt = get_unit_evidence_bundle(unit_id, data.get("unit_evidence_bundles"))
    if prebuilt is not None:
        return prebuilt

    quality_data = data.get("quality_data") or {}
    struct_data = quality_data.get("struct_data") or {}
    gk = gatekeeping_map.get(unit_id) or {}
    tree = _coerce_document_section_tree(struct_data.get("section_tree"), list(evidence_map.values()))
    pool = _coerce_evidence_pool(struct_data.get("evidence_pool"), evidence_map)
    matched_ids = locate_unit_sections(unit_spec, tree)
    extracted_parameters = list(
        struct_data.get("extracted_parameters")
        or quality_data.get("extracted_parameters")
        or []
    )
    return build_unit_evidence_bundle(
        unit_spec=unit_spec,
        matched_section_ids=matched_ids,
        evidence_pool=pool,
        gatekeeping_status=str(gk.get("status") or "pass"),
        warnings=[str(item) for item in (gk.get("issues") or []) if item],
        extracted_parameters=extracted_parameters,
    )


def _format_rule_prompt_line(rule: dict[str, Any], deterministic_by_rule_id: dict[str, Any] | None = None) -> str:
    rule_id = str(rule.get("rule_id") or "")
    rule_text = str(rule.get("rule_text") or rule.get("rule_desc") or "")
    deterministic = (deterministic_by_rule_id or {}).get(rule_id) or {}
    suffix = ""
    if deterministic:
        suffix = (
            f" [deterministic: status={deterministic.get('execution_status')}, "
            f"passed={deterministic.get('passed')}]"
        )
    return f"- {rule_id}: {rule_text}{suffix}"


def _build_unit_agent_prompt(
    *,
    unit_id: str,
    unit_payload: dict[str, Any],
    unit_spec: dict[str, Any],
    bundle: UnitEvidenceBundle,
    data: dict[str, Any],
    matched_signals: list[str],
    enriched_unit_spec: dict[str, Any],
) -> str:
    import json

    intake = data.get("quality_data", {}).get("intake_data", {}) or data.get("intake_data", {})
    primary_lines = []
    for ev in bundle.primary_evidences:
        if not isinstance(ev, dict):
            continue
        text = str(ev.get("excerpt") or ev.get("quote") or ev.get("summary") or "")[:400]
        if text:
            primary_lines.append(
                f"- evidence_id={ev.get('evidence_id', '')}: {text}"
            )
    rule_lines = [_format_rule_prompt_line(item) for item in unit_spec.get("rules", []) or []]
    deterministic_results = enriched_unit_spec.get("deterministic_rule_results") or []
    if deterministic_results:
        deterministic_by_rule_id = {
            str(item.get("rule_id") or ""): item
            for item in deterministic_results
            if isinstance(item, dict)
        }
        rule_lines = [
            _format_rule_prompt_line(item, deterministic_by_rule_id)
            for item in unit_spec.get("rules", []) or []
        ]
    prompt = (
        f"你是 {unit_payload.get('name', unit_id)}。\n"
        f"职责: {unit_payload.get('role', '')}\n"
        f"本单元由材料信号 {', '.join(matched_signals[:8])} 触发分派。\n"
        f"review_id={intake.get('review_id', '')}\n"
        f"门禁状态: {bundle.gatekeeping_status}\n"
        f"告警: {'；'.join(bundle.warnings)}\n\n"
        "=== 待审文档证据 ===\n"
        + ("\n".join(primary_lines) if primary_lines else "无主证据")
        + "\n===\n\n"
        + "=== 本单元必须逐条判定的规则 ===\n"
        + ("\n".join(rule_lines) if rule_lines else "无规则")
        + "\n===\n\n"
        f"review_rules={json.dumps(data.get('review_rules', []), ensure_ascii=False)[:3000]}\n"
        "只基于上述证据与规则形成知识型审查 finding；evidence_ids 必须来自证据列表。\n"
        "依据不足时 judgment=insufficient_evidence；不得声称已完成仿真/试验/数值复算。\n"
    )
    if deterministic_results:
        prompt += (
            "\n\n=== 定量规则确定性预检结果（LLM 只解释上下文，不重新口算）===\n"
            + format_rule_execution_prompt_section(deterministic_results)
            + "\n===\n"
        )
    return prompt


def _unit_finding_to_gnc_dict(
    finding: UnitFinding,
    *,
    unit_id: str,
    unit_payload: dict[str, Any],
    execution: str,
) -> dict[str, Any]:
    unit_name = str(unit_payload.get("name") or unit_id)
    unit_group = str(unit_payload.get("unit_group") or "")
    return {
        "finding_id": finding.finding_id,
        "agent_id": unit_id,
        "expert_role": unit_name,
        "discipline": unit_group,
        "title": finding.description[:120] if finding.description else unit_name,
        "description": finding.description,
        "severity": finding.severity,
        "judgment": "not_satisfied" if finding.severity in {"critical", "major"} else "insufficient_evidence",
        "evidence_ids": list(finding.evidence_refs),
        "rule_ids": [finding.rule_id] if finding.rule_id else [],
        "source_quotes": [],
        "recommendation": finding.recommendation,
        "confidence": 0.0,
        "metadata": {"unit_group": unit_group, "unit_key": unit_id, "execution": execution},
    }


def _rule_result_dict_needs_finding(rule_result: dict[str, Any]) -> bool:
    execution_status = str(rule_result.get("execution_status") or "")
    if execution_status == "insufficient_evidence":
        return True
    if execution_status == "deterministic_checked":
        return not bool(rule_result.get("passed", True))
    if execution_status in {"error", "failed"}:
        return not bool(rule_result.get("passed", True))
    return not bool(rule_result.get("passed", True)) and execution_status not in {"", "llm_checked"}


def _rule_result_to_finding(
    rule_result: dict[str, Any],
    *,
    unit_id: str,
    unit_payload: dict[str, Any],
) -> dict[str, Any]:
    rule_id = str(rule_result.get("rule_id") or "UNKNOWN")
    rule_desc = str(rule_result.get("rule_desc") or rule_id)
    reasoning = str(rule_result.get("reasoning") or "")
    execution_status = str(rule_result.get("execution_status") or "")
    issues = [str(item) for item in (rule_result.get("issues") or []) if item]
    evidence_refs = [str(item) for item in (rule_result.get("evidence_refs") or []) if item]

    if execution_status == "insufficient_evidence":
        judgment = "insufficient_evidence"
        severity = "major"
        title = f"{rule_desc} 证据不足"
        recommendation = "补充规则所需参数或证据后再复核。"
    else:
        judgment = "not_satisfied"
        severity = "critical" if execution_status == "deterministic_checked" else "major"
        title = f"{rule_desc} 未通过"
        recommendation = "依据定量预检结论修订设计或补充论证。"

    description = reasoning
    if issues:
        description = f"{reasoning} 问题: {'；'.join(issues)}".strip()

    unit_name = str(unit_payload.get("name") or unit_id)
    unit_group = str(unit_payload.get("unit_group") or "")
    return {
        "finding_id": f"{unit_id}-rule-{rule_id}",
        "agent_id": unit_id,
        "expert_role": unit_name,
        "discipline": unit_group,
        "title": title[:120],
        "description": description or title,
        "severity": severity,
        "judgment": judgment,
        "evidence_ids": evidence_refs,
        "rule_ids": [rule_id],
        "source_quotes": [],
        "recommendation": recommendation,
        "confidence": 0.85 if execution_status == "deterministic_checked" else 0.55,
        "metadata": {
            "unit_group": unit_group,
            "unit_key": unit_id,
            "execution": "deterministic",
            "rule_id": rule_id,
            "execution_status": execution_status,
            "source": "rule_result",
        },
    }


def _finding_rule_ids(finding: dict[str, Any]) -> set[str]:
    rule_ids = {str(item) for item in (finding.get("rule_ids") or []) if item}
    meta_rule_id = str((finding.get("metadata") or {}).get("rule_id") or "")
    if meta_rule_id:
        rule_ids.add(meta_rule_id)
    return rule_ids


def _merge_rule_results_into_findings(
    llm_findings: list[dict[str, Any]],
    rule_results: list[dict[str, Any]],
    *,
    unit_id: str,
    unit_payload: dict[str, Any],
) -> list[dict[str, Any]]:
    """Promote deterministic rule failures into findings; deterministic wins on rule_id."""
    deterministic_rule_ids: set[str] = set()
    rule_findings: list[dict[str, Any]] = []
    for rule_result in rule_results:
        if not isinstance(rule_result, dict):
            continue
        rule_id = str(rule_result.get("rule_id") or "")
        execution_status = str(rule_result.get("execution_status") or "")
        if rule_id and execution_status in {
            "deterministic_checked",
            "insufficient_evidence",
            "error",
            "failed",
        }:
            deterministic_rule_ids.add(rule_id)
        if not _rule_result_dict_needs_finding(rule_result):
            continue
        rule_findings.append(
            _rule_result_to_finding(rule_result, unit_id=unit_id, unit_payload=unit_payload)
        )

    filtered_llm = [
        item
        for item in llm_findings
        if not (_finding_rule_ids(item) & deterministic_rule_ids)
    ]
    return rule_findings + filtered_llm


def _blocked_gatekeeping_finding(
    unit_id: str,
    unit_payload: dict[str, Any],
    matched_signals: list[str],
    *,
    summary: str,
) -> dict[str, Any]:
    unit_name = str(unit_payload.get("name") or unit_id)
    unit_group = str(unit_payload.get("unit_group") or "")
    return {
        "finding_id": f"{unit_id}-blocked-1",
        "agent_id": unit_id,
        "expert_role": unit_name,
        "discipline": unit_group,
        "title": f"{unit_name} 模板门禁阻断",
        "description": summary or f"{unit_name} 因模板门禁 hard_fail 未开展深审。",
        "severity": "major",
        "judgment": "insufficient_evidence",
        "evidence_ids": [],
        "rule_ids": [],
        "source_quotes": [],
        "recommendation": "补齐缺失主章节或模板要求后再提交该单元审查。",
        "confidence": 0.0,
        "metadata": {
            "unit_group": unit_group,
            "unit_key": unit_id,
            "execution": "blocked",
            "matched_signals": matched_signals[:6],
            "source": "gatekeeping_placeholder",
        },
    }


def _legacy_placeholder_finding(
    unit_id: str,
    unit_payload: dict[str, Any],
    matched_signals: list[str],
    evidence_subset: list[dict[str, Any]],
    *,
    reason: str,
) -> dict[str, Any]:
    unit_name = str(unit_payload.get("name") or unit_id)
    unit_group = str(unit_payload.get("unit_group") or "")
    evidence_ids = [str(ev.get("evidence_id")) for ev in evidence_subset if ev.get("evidence_id")]
    return {
        "finding_id": f"{unit_id}-det-1",
        "agent_id": unit_id,
        "expert_role": unit_name,
        "discipline": unit_group,
        "title": f"{unit_name} 待模型/专家复核",
        "description": (
            f"已按材料信号分派 {unit_name}（命中: {', '.join(matched_signals[:6]) or '材料角色'}）。"
            f"{reason} 已绑定 {len(evidence_ids)} 条候选证据，转人工/模型复核。"
        ),
        "severity": "info",
        "judgment": "insufficient_evidence",
        "evidence_ids": evidence_ids,
        "rule_ids": [],
        "source_quotes": [],
        "recommendation": "在配置审查模型后由该单元基于绑定证据形成领域审查发现。",
        "confidence": 0.0,
        "metadata": {"unit_group": unit_group, "unit_key": unit_id, "execution": "deterministic"},
    }


def _unit_review_result_to_legacy(
    unit_id: str,
    unit_payload: dict[str, Any],
    matched_signals: list[str],
    evidence_subset: list[dict[str, Any]],
    result: UnitReviewResult,
    *,
    execution: str,
    assignment_reason: str = "",
) -> tuple[str, dict[str, Any], list[dict[str, Any]]]:
    unit_name = str(unit_payload.get("name") or unit_id)
    unit_group = str(unit_payload.get("unit_group") or "")
    rule_results = [item.model_dump(mode="json") for item in result.rule_results]

    llm_findings: list[dict[str, Any]] = [
        _unit_finding_to_gnc_dict(item, unit_id=unit_id, unit_payload=unit_payload, execution=execution)
        for item in result.findings
    ]
    findings = _merge_rule_results_into_findings(
        llm_findings,
        rule_results,
        unit_id=unit_id,
        unit_payload=unit_payload,
    )
    if not findings and result.status == "placeholder":
        execution = "blocked"
        findings = [
            _blocked_gatekeeping_finding(
                unit_id,
                unit_payload,
                matched_signals,
                summary=result.summary,
            )
        ]
    elif not findings and execution == "deterministic":
        findings = [
            _legacy_placeholder_finding(
                unit_id,
                unit_payload,
                matched_signals,
                evidence_subset,
                reason=assignment_reason or "单元 LLM 审查未执行。",
            )
        ]

    status_map = {
        "completed": "ok" if execution == "llm" else "degraded",
        "placeholder": "placeholder",
        "error": "failed",
        "incomplete": "degraded",
    }
    review = {
        "agent_id": unit_id,
        "unit_key": unit_id,
        "unit_group": unit_group,
        "reviewer": unit_name,
        "discipline": unit_group,
        "status": status_map.get(result.status, "degraded"),
        "execution": execution,
        "matched_signals": matched_signals,
        "summary": result.summary,
        "knowledge_gap": result.knowledge_gap,
        "confidence": result.confidence,
        "rule_results": rule_results,
        "evidence_ids": list(result.evidence_ids),
        "is_blocked": result.is_blocked,
        "finding_count": len(findings),
        "findings": findings,
        "completed": result.status != "error",
    }
    if assignment_reason:
        review["assignment_reason"] = assignment_reason
    return unit_id, review, findings


def run_unit_review(
    unit: dict[str, Any],
    data: dict[str, Any],
    evidence_map: dict[str, dict[str, Any]],
    *,
    domain_id: str = "aerospace_review",
    model_id: str | None = None,
    debug_mode: bool = False,
) -> tuple[str, dict[str, Any], list[dict[str, Any]]]:
    """Run one AD/AC unit review via source-equivalent execute_unit_rules."""
    unit_id = str(unit.get("unit_id") or "")
    matched_signals = list(unit.get("matched_signals") or [])
    catalog = review_units_for_domain(domain_id)
    unit_payload = catalog.get(unit_id, {})
    unit_name = str(unit.get("unit_name") or unit_payload.get("name") or unit_id)

    quality_data = data.get("quality_data") or {}
    gatekeeping_map = _index_gatekeeping_results(quality_data)
    unit_spec = _resolve_unit_spec_for_review(unit_id, unit_name, quality_data, catalog)
    bundle = _resolve_unit_evidence_bundle(unit_id, unit_spec, data, evidence_map, gatekeeping_map)

    evidences = list(evidence_map.values())
    evidence_subset = _evidence_subset_for_unit(unit_payload, evidences)
    llm_enabled = _llm_enabled()

    def _run_agent_func(review_bundle: UnitEvidenceBundle, enriched_spec: dict[str, Any]) -> Any:
        if not llm_enabled:
            class StubOut:
                rule_results: list[RuleExecutionResult] = []
                findings: list[Any] = []
                summary = "单元 LLM 审查未执行，保留定量规则预检结果。"
                completed = True
                knowledge_gap = False
                confidence = 0.0

            return StubOut()

        from data_agent.integrations.satellite_review.gnc_agents import build_unit_agent
        from data_agent.integrations.satellite_review.gnc_schemas import GNCCommitteeOutput
        from data_agent.agno_structured import run_agent_with_validation

        agent = build_unit_agent(unit_id, unit_payload, model_id=model_id, debug_mode=debug_mode)
        prompt = _build_unit_agent_prompt(
            unit_id=unit_id,
            unit_payload=unit_payload,
            unit_spec=unit_spec,
            bundle=review_bundle,
            data=data,
            matched_signals=matched_signals,
            enriched_unit_spec=enriched_spec,
        )
        return run_agent_with_validation(agent, prompt, GNCCommitteeOutput)

    try:
        result = execute_unit_rules(
            unit_spec=unit_spec,
            agent_id=unit_id,
            bundle=bundle,
            run_agent_func=_run_agent_func,
        )
        execution = "llm" if llm_enabled and result.status != "placeholder" else "deterministic"
        if result.status == "placeholder":
            execution = "blocked"
        assignment_reason = ""
        if not llm_enabled:
            assignment_reason = "单元 LLM 审查已关闭（GNC_REVIEW_UNITS_LLM_ENABLED=0）。"
        return _unit_review_result_to_legacy(
            unit_id,
            unit_payload,
            matched_signals,
            evidence_subset,
            result,
            execution=execution,
            assignment_reason=assignment_reason,
        )
    except Exception as exc:  # noqa: BLE001 - degrade any LLM/runtime failure to deterministic
        logger.warning("[review_units] unit %s degraded to deterministic: %s", unit_id, exc)
        fallback = UnitReviewResult(
            unit_key=unit_id,
            unit_name=unit_name,
            agent_id=unit_id,
            status="error",
            summary=f"审查执行过程遭遇异常: {exc}",
            knowledge_gap=True,
        )
        return _unit_review_result_to_legacy(
            unit_id,
            unit_payload,
            matched_signals,
            evidence_subset,
            fallback,
            execution="deterministic",
            assignment_reason="审查模型不可用或执行失败，降级为确定性占位审查。",
        )


__all__ = [
    "build_unit_evidence_bundles_for_workflow",
    "build_unit_template_gatekeeping",
    "run_unit_review",
    "select_units_by_signals",
]
