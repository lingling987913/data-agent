"""Deterministic execution for quantitative review rules."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from typing import Any

from data_agent.review.p0_schemas import RuleExecutionResult, ToolCallEvidence, UnitEvidenceBundle
from data_agent.review.unit_normalization_service import (
    convert_value,
    normalize_unit as _shared_normalize_unit,
)


_CALC_MODULE = None
_COMPARE_ALIASES = {
    "<": "lt",
    "<=": "le",
    "≤": "le",
    "lt": "lt",
    "le": "le",
    ">": "gt",
    ">=": "ge",
    "≥": "ge",
    "gt": "gt",
    "ge": "ge",
    "=": "eq",
    "==": "eq",
    "eq": "eq",
}

_LEGACY_UNIT_LABELS = {
    "deg": "度",
    "rad": "弧度",
    "mrad": "毫弧度",
    "ms": "毫秒",
    "s": "秒",
    "min": "分钟",
    "Hz": "赫兹",
    "dB": "分贝",
    "deg/s": "度/秒",
    "deg/min": "度/分钟",
    "deg/h": "度/小时",
    "rad/s": "弧度/秒",
    "rad/h": "弧度/小时",
    "N·m": "牛顿米",
    "N·m·s": "牛米秒",
    "mN·s": "毫牛秒",
    "mN·m·s": "毫牛米秒",
    "m/s^2": "米每秒平方",
    "g": "重力加速度",
    "m/s": "米/秒",
    "km/s": "千米/秒",
    "W": "瓦",
    "kW": "千瓦",
    "N": "牛顿",
    "kgf": "千克力",
}


def execute_quantitative_rules(
    unit_spec: dict[str, Any],
    bundle: UnitEvidenceBundle,
) -> list[RuleExecutionResult]:
    """Run deterministic prechecks for quantitative rules in a unit spec."""
    results: list[RuleExecutionResult] = []
    for rule in unit_spec.get("rules", []) or []:
        if not isinstance(rule, dict) or str(rule.get("rule_type", "")).lower() != "quantitative":
            continue
        results.append(execute_quantitative_rule(rule, bundle))
    return results


def execute_quantitative_rule(
    rule: dict[str, Any],
    bundle: UnitEvidenceBundle,
) -> RuleExecutionResult:
    rule_id = str(rule.get("rule_id", "") or "UNKNOWN")
    rule_text = str(rule.get("rule_text", "") or rule.get("rule_desc", "") or "")
    rule_source_refs = _coerce_rule_source_refs(rule.get("rule_source_refs") or rule.get("source_refs"))
    raw_formula = str(rule.get("formula_template", "") or rule.get("formula", "") or "").strip()
    threshold = rule.get("threshold")
    compare = _normalize_compare(rule.get("compare_op", rule.get("compare", "lt")))
    formula, formula_warnings = _normalize_formula_expression(raw_formula, threshold=threshold)
    required_parameters = _coerce_str_list(rule.get("required_parameters", []))
    expected_unit = str(rule.get("unit", "") or "").strip()

    if not formula:
        return _insufficient(rule_id, rule_text, "定量规则缺少 formula_template/formula，无法执行确定性预检。", rule_source_refs)
    if not required_parameters:
        required_parameters = _infer_formula_variables(formula)
    if not required_parameters:
        return _insufficient(rule_id, rule_text, "定量规则未声明 required_parameters，且无法从公式推断变量。", rule_source_refs)

    # 审查断点2：从规则的 applicability.tags 提取工况标签，用于参数上下文匹配
    applicability = rule.get("applicability") or {}
    rule_applicability_tags = []
    if isinstance(applicability, dict):
        tags = applicability.get("tags", [])
        if isinstance(tags, list):
            rule_applicability_tags = [str(tag) for tag in tags if tag]
        elif tags:
            rule_applicability_tags = [str(tags)]
        # 如果 applicability 包含 condition 字段，也作为补充标签
        condition = applicability.get("condition", "")
        if condition:
            rule_applicability_tags.append(str(condition))

    binding = bind_rule_parameters(
        required_parameters=required_parameters,
        parameter_aliases=rule.get("parameter_aliases", {}),
        expected_unit=expected_unit,
        unit_key=bundle.unit_key,
        extracted_parameters=bundle.extracted_parameters,
        rule_applicability_tags=rule_applicability_tags,
    )
    if binding["missing_parameters"]:
        return RuleExecutionResult(
            rule_id=rule_id,
            rule_desc=rule_text,
            passed=False,
            evidence_refs=[],
            reasoning="定量预检证据不足: 缺少参数 " + ", ".join(binding["missing_parameters"]),
            calculation={
                "formula": formula,
                "threshold": threshold,
                "compare": compare,
                "missing_parameters": binding["missing_parameters"],
                "binding_warnings": [*formula_warnings, *binding["warnings"]],
            },
            parameter_refs=binding["parameter_refs"],
            tool_calls=[
                _build_tool_call_evidence(
                    tool_name="parameter_binding",
                    tool_type="parameter_binding",
                    status="insufficient_evidence",
                    input_payload={
                        "required_parameters": required_parameters,
                        "parameter_aliases": rule.get("parameter_aliases", {}),
                        "expected_unit": expected_unit,
                        "unit_key": bundle.unit_key,
                    },
                    output_payload={
                        "missing_parameters": binding["missing_parameters"],
                        "binding_warnings": [*formula_warnings, *binding["warnings"]],
                        "parameter_refs": binding["parameter_refs"],
                    },
                    evidence_refs=[],
                    source_refs=rule_source_refs,
                    confidence=0.4,
                    error_message="缺少定量规则所需参数",
                )
            ],
            verification_method="deterministic_calculation",
            rule_source_refs=rule_source_refs,
            execution_status="insufficient_evidence",
        )

    calc_input = {
        "formula": formula,
        "params": binding["params"],
        "threshold": threshold,
        "compare": compare,
        "unit": expected_unit,
    }
    calc = _load_calc_module().evaluate_formula(calc_input)
    if calc.get("error"):
        status = str(calc.get("execution_status", "") or "error")
        return RuleExecutionResult(
            rule_id=rule_id,
            rule_desc=rule_text,
            passed=False,
            evidence_refs=[] if status == "insufficient_evidence" else binding["evidence_refs"],
            reasoning=f"定量预检未完成: {calc.get('error', '')}",
            calculation={**calc, "binding_warnings": [*formula_warnings, *binding["warnings"]]},
            parameter_refs=binding["parameter_refs"],
            tool_calls=[
                _build_tool_call_evidence(
                    tool_name="numerical-verification/calc.py",
                    tool_type="calculation",
                    status=status,
                    input_payload=calc_input,
                    output_payload=calc,
                    evidence_refs=[] if status == "insufficient_evidence" else binding["evidence_refs"],
                    source_refs=rule_source_refs,
                    confidence=0.55 if status == "insufficient_evidence" else 0.2,
                    error_message=str(calc.get("error", "") or ""),
                )
            ],
            verification_method="deterministic_calculation",
            rule_source_refs=rule_source_refs,
            execution_status=status,
        )

    passed = bool(calc.get("passed")) if calc.get("passed") is not None else True
    result_value = calc.get("result")
    threshold_value = calc.get("threshold")
    reasoning = (
        f"定量预检完成: 计算值={result_value}{expected_unit or ''}, "
        f"阈值={threshold_value}, 比较={compare}, 结论={'通过' if passed else '不通过'}。"
    )
    return RuleExecutionResult(
        rule_id=rule_id,
        rule_desc=rule_text,
        passed=passed,
        evidence_refs=binding["evidence_refs"],
        reasoning=reasoning,
        calculation={**calc, "binding_warnings": [*formula_warnings, *binding["warnings"]]},
        parameter_refs=binding["parameter_refs"],
        tool_calls=[
            _build_tool_call_evidence(
                tool_name="numerical-verification/calc.py",
                tool_type="calculation",
                status="ok",
                input_payload=calc_input,
                output_payload=calc,
                evidence_refs=binding["evidence_refs"],
                source_refs=rule_source_refs,
                confidence=0.95,
            )
        ],
        verification_method="deterministic_calculation",
        # 审查断点1：把模板规则 source_refs 带到规则判定结果，供 RID 回填 rule_source_refs。
        rule_source_refs=rule_source_refs,
        execution_status="deterministic_checked",
    )


def _build_tool_call_evidence(
    *,
    tool_name: str,
    tool_type: str,
    status: str,
    input_payload: dict[str, Any],
    output_payload: dict[str, Any],
    evidence_refs: list[str],
    source_refs: list[dict[str, Any]],
    confidence: float,
    error_message: str = "",
) -> ToolCallEvidence:
    return ToolCallEvidence(
        tool_name=tool_name,
        tool_type=tool_type,
        input=input_payload,
        output=output_payload,
        status=status,
        error_message=error_message,
        source_refs=source_refs,
        evidence_refs=evidence_refs,
        confidence=confidence,
    )


def bind_rule_parameters(
    *,
    required_parameters: list[str],
    parameter_aliases: Any,
    expected_unit: str,
    extracted_parameters: list[dict[str, Any]],
    unit_key: str = "",
    rule_applicability_tags: list[str] | None = None,
) -> dict[str, Any]:
    aliases = _normalize_aliases(parameter_aliases)
    available = [item for item in extracted_parameters or [] if isinstance(item, dict)]
    params: dict[str, float] = {}
    refs: list[dict[str, Any]] = []
    evidence_refs: set[str] = set()
    missing: list[str] = []
    warnings: list[str] = []

    for param_name in required_parameters:
        candidates = _find_parameter_candidates(param_name, aliases.get(param_name, []), available)
        compatible_candidates = []
        for candidate in candidates:
            conversion = _conversion_factor(str(candidate.get("unit", "") or ""), expected_unit)
            if conversion is not None:
                compatible_candidates.append((candidate, conversion))
        # 审查断点2：优先按 context_tags 重叠度排序，其次按 stage 关键词和置信度
        if rule_applicability_tags:
            compatible_candidates.sort(
                key=lambda pair: (
                    _context_tags_match_score(pair[0], rule_applicability_tags),
                    _stage_match_score(pair[0], unit_key),
                    float(pair[0].get("confidence", 0.0) or 0.0),
                ),
                reverse=True,
            )
        else:
            compatible_candidates.sort(
                key=lambda pair: (
                    _stage_match_score(pair[0], unit_key),
                    float(pair[0].get("confidence", 0.0) or 0.0),
                ),
                reverse=True,
            )
        if not candidates:
            missing.append(param_name)
            continue
        if not compatible_candidates:
            missing.append(param_name)
            warnings.append(f"参数 {param_name} 未找到与规则单位 {expected_unit} 兼容的候选。")
            continue

        chosen, factor = compatible_candidates[0]
        if len(compatible_candidates) > 1:
            if rule_applicability_tags:
                warnings.append(f"参数 {param_name} 命中多个候选，已优先按规则工况标签、审查单元关键词和置信度选择。")
            else:
                warnings.append(f"参数 {param_name} 命中多个候选，已优先按审查单元/工况关键词和置信度选择。")
        try:
            raw_value = float(chosen.get("value"))
            converted_value = raw_value * factor
            params[param_name] = converted_value
        except (TypeError, ValueError):
            missing.append(param_name)
            warnings.append(f"参数 {param_name} 的候选值无法转为数值。")
            continue
        actual_unit = str(chosen.get("unit", "") or "")
        if expected_unit and _normalize_unit(actual_unit) != _normalize_unit(expected_unit):
            warnings.append(f"参数 {param_name} 已从 {actual_unit} 换算为 {expected_unit}。")
        evidence_id = str(chosen.get("source_evidence_id", "") or "")
        if evidence_id:
            evidence_refs.add(evidence_id)
        refs.append({
            "parameter": param_name,
            "parameter_id": chosen.get("parameter_id", ""),
            "name": chosen.get("name", ""),
            "normalized_name": chosen.get("normalized_name", ""),
            "value": chosen.get("value"),
            "bound_value": converted_value,
            "unit": chosen.get("unit", ""),
            "bound_unit": expected_unit or chosen.get("unit", ""),
            "confidence": chosen.get("confidence", 0.0),
            "source_section_id": chosen.get("source_section_id", ""),
            "source_evidence_id": evidence_id,
            "block_ids": chosen.get("block_ids", []),
            "source_text": chosen.get("source_text", ""),
            "context_tags": chosen.get("context_tags", []),
        })

    return {
        "params": params,
        "parameter_refs": refs,
        "evidence_refs": sorted(evidence_refs),
        "missing_parameters": missing,
        "warnings": warnings,
    }


def format_rule_execution_prompt_section(results: list[Any]) -> str:
    if not results:
        return "无定量规则预检结果"
    lines = []
    for raw in results:
        result = raw.model_dump() if hasattr(raw, "model_dump") else dict(raw)
        calc = result.get("calculation") or {}
        parameter_refs = result.get("parameter_refs") or []
        refs = ", ".join(
            str(ref.get("parameter_id") or ref.get("name") or ref.get("parameter"))
            for ref in parameter_refs
        ) or "无"
        lines.append(
            "- "
            f"{result.get('rule_id')}: status={result.get('execution_status') or 'unknown'}; "
            f"passed={result.get('passed')}; result={calc.get('result')}; "
            f"threshold={calc.get('threshold')}; compare={calc.get('compare')}; "
            f"parameter_refs={refs}; reasoning={result.get('reasoning', '')}"
        )
    return "\n".join(lines)


def _load_calc_module():
    global _CALC_MODULE
    if _CALC_MODULE is not None:
        return _CALC_MODULE
    script_path = (
        Path(__file__).resolve().parents[2]
        / "skills"
        / "numerical-verification"
        / "scripts"
        / "calc.py"
    )
    spec = importlib.util.spec_from_file_location("aq_aero_numerical_calc", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载数值计算脚本: {script_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _CALC_MODULE = module
    return module


def _find_parameter_candidates(
    param_name: str,
    aliases: list[str],
    available: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    expected = {_normalize_name(param_name), *(_normalize_name(alias) for alias in aliases)}
    expected.discard("")
    candidates = []
    for item in available:
        names = {
            _normalize_name(str(item.get("normalized_name", "") or "")),
            _normalize_name(str(item.get("name", "") or "")),
        }
        if expected.intersection(names):
            candidates.append(item)
    return candidates


def _normalize_aliases(parameter_aliases: Any) -> dict[str, list[str]]:
    if not isinstance(parameter_aliases, dict):
        return {}
    normalized: dict[str, list[str]] = {}
    for key, value in parameter_aliases.items():
        if isinstance(value, list):
            normalized[str(key)] = [str(item) for item in value if item]
        elif value:
            normalized[str(key)] = [str(value)]
    return normalized


def _conversion_factor(actual_unit: str, expected_unit: str) -> float | None:
    if not expected_unit:
        return 1.0
    actual = _shared_normalize_unit(actual_unit)
    expected = _shared_normalize_unit(expected_unit)
    actual_raw = str(actual_unit or "").strip().lower()
    expected_raw = str(expected_unit or "").strip().lower()
    acceleration_units = {"g0", "m/s^2"}
    if actual_raw == "g" and expected in acceleration_units:
        actual = "g0"
    if expected_raw == "g" and actual in acceleration_units:
        expected = "g0"
    if not actual or not expected:
        return None
    if actual == expected:
        return 1.0
    converted = convert_value(1.0, actual, expected)
    return converted


def _normalize_unit(unit: str) -> str:
    normalized = _shared_normalize_unit(unit)
    if not normalized:
        return str(unit or "").strip()
    return _LEGACY_UNIT_LABELS.get(normalized, normalized)


_UNIT_KEYWORDS = {
    "ad_req_err": ["ad_req_err", "req_err", "需求", "误差", "精度", "姿态确定"],
    "ad_timing": ["ad_timing", "timing", "时序", "采样", "同步"],
    "ad_install": ["ad_install", "install", "安装", "指向", "视场"],
    "ad_algorithm": ["ad_algorithm", "algorithm", "算法", "滤波", "定姿"],
    "ad_simulation": ["ad_simulation", "simulation", "仿真", "验证"],
    "ac_req_err": ["ac_req_err", "req_err", "需求", "误差", "控制精度"],
    "ac_control_law": ["ac_control_law", "control_law", "控制律", "闭环", "稳定"],
    "ac_control_params": ["ac_control_params", "control_params", "控制参数", "角速度", "带宽"],
    "ac_maneuver_law": ["ac_maneuver_law", "maneuver_law", "机动", "操纵"],
    "ac_unloading_law": ["ac_unloading_law", "unloading_law", "卸载"],
    "ac_thruster_layout": ["ac_thruster_layout", "thruster", "推力器"],
    "ac_other_actuator_layout": ["ac_other_actuator_layout", "actuator", "执行机构", "飞轮"],
    "ac_simulation": ["ac_simulation", "simulation", "仿真", "验证"],
}


def _stage_match_score(item: dict[str, Any], unit_key: str) -> int:
    if not unit_key:
        return 0
    keywords = _UNIT_KEYWORDS.get(unit_key, [unit_key, unit_key.replace("_", " ")])
    haystack = " ".join(
        str(item.get(field, "") or "")
        for field in (
            "stage",
            "stage_key",
            "review_stage",
            "condition",
            "working_condition",
            "scenario",
            "source_section_id",
            "source_section_title",
            "source_text",
        )
    ).lower()
    return sum(1 for keyword in keywords if str(keyword).lower() in haystack)


def _context_tags_match_score(item: dict[str, Any], rule_tags: list[str]) -> int:
    """计算参数的 context_tags 与规则标签的重叠度。
    重叠越多分数越高，用于区分同名参数的不同工况（如稳态 vs 机动）。
    """
    if not rule_tags:
        return 0
    param_tags = item.get("context_tags") or []
    if not isinstance(param_tags, list):
        return 0
    param_tags_lower = {str(tag).lower() for tag in param_tags}
    rule_tags_lower = {str(tag).lower() for tag in rule_tags}
    return len(param_tags_lower & rule_tags_lower)


def _normalize_compare(value: Any) -> str:
    return _COMPARE_ALIASES.get(str(value or "").strip().lower(), "lt")


def _normalize_formula_expression(formula: str, *, threshold: Any = None) -> tuple[str, list[str]]:
    """Keep quantitative formula as a scalar expression.

    Some template authors naturally write `x <= threshold` in the formula field
    even though threshold comparison is configured separately. The calculator
    expects a scalar expression, so strip this common pattern and keep an audit
    warning in the calculation result.
    """
    text = str(formula or "").strip()
    if not text:
        return "", []
    if threshold is None:
        return text, []
    match = re.match(
        r"^(?P<lhs>.+?)\s*(?P<op><=|>=|==|=|<|>|≤|≥)\s*threshold\s*$",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        return text, []
    lhs = match.group("lhs").strip()
    if not lhs:
        return text, []
    op = match.group("op")
    return lhs, [f"公式字段包含比较表达式 `{text}`，已按标量表达式 `{lhs}` 执行，比较符 `{op}` 由 compare/threshold 字段处理。"]


def _normalize_name(value: str) -> str:
    return re.sub(r"[\s_：:，,。；;（）()/%\-·]+", "", value or "").lower()


def _coerce_str_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item or "").strip()]
    if value:
        return [str(value)]
    return []


def _coerce_rule_source_refs(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def _infer_formula_variables(formula: str) -> list[str]:
    try:
        module = _load_calc_module()
        validation = module.validate_formula_ast(formula, set())
        missing = validation.get("missing_variables", []) if isinstance(validation, dict) else []
        return [str(item) for item in missing]
    except Exception:
        return []


def _insufficient(
    rule_id: str,
    rule_text: str,
    reason: str,
    rule_source_refs: list[dict[str, Any]] | None = None,
) -> RuleExecutionResult:
    return RuleExecutionResult(
        rule_id=rule_id,
        rule_desc=rule_text,
        passed=False,
        evidence_refs=[],
        reasoning=reason,
        rule_source_refs=rule_source_refs or [],
        execution_status="insufficient_evidence",
        calculation={"error": reason, "execution_status": "insufficient_evidence"},
    )
