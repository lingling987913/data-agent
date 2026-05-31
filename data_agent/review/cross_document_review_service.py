"""Deterministic cross-document review item generation for P0 traceability."""

from __future__ import annotations

import re
from collections import defaultdict

from data_agent.review.p0_schemas import (
    CrossDocumentReviewItem,
    DesignImplementationItem,
    MaterialItem,
    RequirementNode,
    RequirementTraceLink,
    VerificationClaim,
)
from data_agent.review.trace_link_utils import active_trace_links
from data_agent.review.traceability_text_utils import condition_tags
from data_agent.review.unit_normalization_service import convert_value, normalize_unit


REVIEW_ITEM_DEFAULT_SEVERITY: dict[str, str] = {
    "missing_decomposition": "major",
    "missing_design_closure": "major",
    "missing_verification": "major",
    "design_item_without_requirement_basis": "minor",
    "metric_value_mismatch": "critical",
    "metric_unit_mismatch": "major",
    "metric_unit_missing": "major",
    "metric_statistic_mismatch": "major",
    "verification_condition_gap": "major",
    "baseline_version_mismatch": "major",
}


def generate_cross_document_review_items(
    requirements: list[RequirementNode],
    design_items: list[DesignImplementationItem],
    verification_claims: list[VerificationClaim],
    links: list[RequirementTraceLink],
    materials: list[MaterialItem],
) -> list[CrossDocumentReviewItem]:
    """Generate evidence-backed P0 review items from typed traceability objects."""
    active_links = active_trace_links(links)
    completed_verification_ids = {
        claim.verification_id
        for claim in verification_claims
        if claim.status == "completed"
    }
    children_by_parent = defaultdict(list)
    design_by_req = defaultdict(list)
    verification_by_req = defaultdict(list)
    req_by_id = {req.requirement_id: req for req in requirements}
    linked_design_ids: set[str] = set()
    review_items: list[CrossDocumentReviewItem] = []

    for link in active_links:
        if link.link_type == "decomposes":
            children_by_parent[link.source_id].append(link.target_id)
        elif link.link_type == "satisfies":
            design_by_req[link.source_id].append(link.target_id)
            linked_design_ids.add(link.target_id)
        elif (
            link.link_type == "verifies"
            and link.source_id in req_by_id
            and link.target_id in completed_verification_ids
        ):
            verification_by_req[link.source_id].append(link.target_id)

    def add(
        item_type: str,
        artifact_id: str,
        title: str,
        description: str,
        quote: str,
        recommendation: str,
    ) -> None:
        review_items.append(CrossDocumentReviewItem(
            review_item_id=f"p0-{item_type}-{len(review_items) + 1}",
            item_type=item_type,
            severity=_severity_for(item_type),
            title=title,
            description=description,
            impact=_impact_for(item_type),
            recommendation=recommendation,
            source_artifact_ids=[artifact_id],
            evidence_ids=[_evidence_for(artifact_id, requirements, design_items, verification_claims)],
            source_quote=quote,
            status="pending_confirmation" if item_type == "design_item_without_requirement_basis" else "open",
        ))

    for req in requirements:
        if req.requirement_level == "top" and not children_by_parent.get(req.requirement_id):
            add(
                "missing_decomposition",
                req.requirement_id,
                "需求分解不完整",
                f"上级需求 {req.requirement_id} 未发现明确下级分解需求。",
                req.source_quote,
                "补充分系统/专业需求分解，或说明由其他分系统承接。",
            )
        if req.requirement_level == "decomposed" and not design_by_req.get(req.requirement_id):
            add(
                "missing_design_closure",
                req.requirement_id,
                "设计闭合不足",
                f"分解需求 {req.requirement_id} 未发现明确设计实现项。",
                req.source_quote,
                "补充设计实现项、参数配置、算法或接口依据。",
            )
        if req.requirement_level == "decomposed" and not verification_by_req.get(req.requirement_id):
            add(
                "missing_verification",
                req.requirement_id,
                "验证覆盖不足",
                f"分解需求 {req.requirement_id} 未发现仿真、分析、试验或检查依据。",
                req.source_quote,
                "补充验证项、工况和验收准则，或说明验证边界。",
            )

    for item in design_items:
        if item.design_item_id not in linked_design_ids:
            add(
                "design_item_without_requirement_basis",
                item.design_item_id,
                "设计实现项未建立明确的上游需求依据",
                f"设计实现项 {item.design_item_id} 未显式关联上游需求。",
                item.source_quote,
                "确认该设计项的需求来源，或补充接口/标准/工程约束依据。",
            )

    review_items.extend(_detect_design_metric_items(requirements, design_items, active_links, start_index=len(review_items) + 1))
    review_items.extend(_detect_metric_and_condition_items(
        requirements,
        verification_claims,
        active_links,
        start_index=len(review_items) + 1,
    ))
    review_items.extend(_detect_baseline_review_items(materials, requirements, design_items, verification_claims))
    return review_items


def _detect_design_metric_items(
    requirements: list[RequirementNode],
    design_items: list[DesignImplementationItem],
    links: list[RequirementTraceLink],
    start_index: int,
) -> list[CrossDocumentReviewItem]:
    review_items: list[CrossDocumentReviewItem] = []
    req_by_id = {req.requirement_id: req for req in requirements}
    design_by_id = {item.design_item_id: item for item in design_items}
    for link in links:
        if link.link_type != "satisfies":
            continue
        req = req_by_id.get(link.source_id)
        design = design_by_id.get(link.target_id)
        if not req or not design:
            continue
        if req.metric_id and design.metric_id and req.metric_id != design.metric_id:
            continue
        review_items.extend(_metric_pair_review_items(
            req=req,
            target_id=design.design_item_id,
            target_value=design.observed_value,
            target_unit=design.unit,
            target_quote=design.source_quote,
            target_evidence_id=design.source_evidence_id,
            target_kind="设计实现项",
            start_index=start_index + len(review_items),
        ))
    return review_items


def _active_verifies_pairs(active_links: list[RequirementTraceLink]) -> set[tuple[str, str]]:
    return {
        (link.source_id, link.target_id)
        for link in active_links
        if link.link_type == "verifies"
    }


def _detect_metric_and_condition_items(
    requirements: list[RequirementNode],
    verification_claims: list[VerificationClaim],
    active_links: list[RequirementTraceLink],
    start_index: int,
) -> list[CrossDocumentReviewItem]:
    review_items: list[CrossDocumentReviewItem] = []
    req_by_id = {req.requirement_id: req for req in requirements}
    verifies_pairs = _active_verifies_pairs(active_links)
    for claim in verification_claims:
        if claim.status != "completed":
            continue
        for req_id in claim.verifies_requirement_ids:
            if (req_id, claim.verification_id) not in verifies_pairs:
                continue
            req = req_by_id.get(req_id)
            if not req:
                continue
            if req.target_value is not None and claim.observed_value is not None:
                if req.metric_id and claim.metric_id and req.metric_id != claim.metric_id:
                    continue
                pair_items = _metric_pair_review_items(
                    req=req,
                    target_id=claim.verification_id,
                    target_value=claim.observed_value,
                    target_unit=claim.unit,
                    target_quote=claim.source_quote,
                    target_evidence_id=claim.source_evidence_id,
                    target_kind="验证项",
                    start_index=start_index + len(review_items),
                )
                review_items.extend(pair_items)
            missing_tags = [tag for tag in req.condition_tags if tag not in condition_tags(claim.source_quote)]
            if missing_tags:
                review_items.append(CrossDocumentReviewItem(
                    review_item_id=f"p0-verification_condition_gap-{start_index + len(review_items)}",
                    item_type="verification_condition_gap",
                    severity=_severity_for("verification_condition_gap"),
                    title="仿真/验证工况覆盖不足",
                    description=f"{req.requirement_id} 包含工况标签 {', '.join(missing_tags)}，验证项 {claim.verification_id} 未体现对应工况覆盖。",
                    impact="验证工况未覆盖需求边界或故障场景时，不能形成完整验证覆盖结论。",
                    recommendation="补充边界、故障或降级工况验证，或说明工况裁剪依据。",
                    source_artifact_ids=[req.requirement_id],
                    target_artifact_ids=[claim.verification_id],
                    evidence_ids=[req.source_evidence_id, claim.source_evidence_id],
                    source_quote=f"{req.source_quote}\n{claim.source_quote}",
                ))
    return review_items


def _metric_pair_review_items(
    *,
    req: RequirementNode,
    target_id: str,
    target_value: float | None,
    target_unit: str,
    target_quote: str,
    target_evidence_id: str,
    target_kind: str,
    start_index: int,
) -> list[CrossDocumentReviewItem]:
    if req.target_value is None or target_value is None:
        return []
    review_items: list[CrossDocumentReviewItem] = []
    source_unit = normalize_unit(target_unit or "")
    req_unit = normalize_unit(req.unit or "")
    missing_sides: list[str] = []
    if not req_unit:
        missing_sides.append(f"需求 {req.requirement_id}")
    if not source_unit:
        missing_sides.append(f"{target_kind} {target_id}")
    if missing_sides:
        review_items.append(CrossDocumentReviewItem(
            review_item_id=f"p0-metric_unit_missing-{start_index + len(review_items)}",
            item_type="metric_unit_missing",
            severity=_severity_for("metric_unit_missing"),
            title="指标单位缺失",
            description=(
                f"{req.requirement_id} 与 {target_kind} {target_id} 均给出数值，但"
                f"{'、'.join(missing_sides)} 未标注单位，无法形成可靠换算或满足性比较。"
            ),
            impact="单侧或双侧缺少单位时，指标数值不能直接用于闭合判定。",
            recommendation="在需求、设计或验证证据中补充指标单位，并统一审查基线中的量纲口径。",
            source_artifact_ids=[req.requirement_id],
            target_artifact_ids=[target_id],
            evidence_ids=[req.source_evidence_id, target_evidence_id],
            source_quote=f"{req.source_quote}\n{target_quote}",
        ))
        return review_items

    converted = _convert_value(target_value, target_unit, req.unit)
    if converted is None:
        review_items.append(CrossDocumentReviewItem(
            review_item_id=f"p0-metric_unit_mismatch-{start_index + len(review_items)}",
            item_type="metric_unit_mismatch",
            severity=_severity_for("metric_unit_mismatch"),
            title="指标单位不一致",
            description=f"{req.requirement_id} 使用单位 {req.unit or '未标注'}，{target_kind} {target_id} 使用单位 {target_unit or '未标注'}，当前规则无法可靠换算。",
            impact="指标单位或量纲不一致时，验证结论不能直接支撑需求满足性判断。",
            recommendation="补充单位换算依据，或统一需求、设计与验证结果中的指标单位。",
            source_artifact_ids=[req.requirement_id],
            target_artifact_ids=[target_id],
            evidence_ids=[req.source_evidence_id, target_evidence_id],
            source_quote=f"{req.source_quote}\n{target_quote}",
        ))
        return review_items
    if not _metric_satisfies(req.comparator, req.target_value, converted):
        review_items.append(CrossDocumentReviewItem(
            review_item_id=f"p0-metric_value_mismatch-{start_index + len(review_items)}",
            item_type="metric_value_mismatch",
            severity=_severity_for("metric_value_mismatch"),
            title="指标数值不一致",
            description=f"{req.requirement_id} 要求 {req.comparator or '='} {req.target_value:g} {req.unit}，{target_kind} {target_id} 给出 {target_value:g} {target_unit}。",
            impact="关键技术指标未形成满足性证据，应优先进入 RID 候选。",
            recommendation="复核指标口径、统计方法和验收准则；必要时补充换算或修订设计/仿真结论。",
            source_artifact_ids=[req.requirement_id],
            target_artifact_ids=[target_id],
            evidence_ids=[req.source_evidence_id, target_evidence_id],
            source_quote=f"{req.source_quote}\n{target_quote}",
        ))
    req_statistic = _statistic_basis(req.source_quote)
    target_statistic = _statistic_basis(target_quote)
    if req_statistic and target_statistic and req_statistic != target_statistic:
        review_items.append(CrossDocumentReviewItem(
            review_item_id=f"p0-metric_statistic_mismatch-{start_index + len(review_items)}",
            item_type="metric_statistic_mismatch",
            severity=_severity_for("metric_statistic_mismatch"),
            title="指标统计口径不一致",
            description=f"{req.requirement_id} 使用 {req_statistic} 口径，{target_kind} {target_id} 使用 {target_statistic} 口径，未发现转换说明。",
            impact="统计口径不一致时，指标数值即使接近也不能直接用于闭合判定。",
            recommendation="补充 RMS、3σ、最大值等统计口径的转换依据，或统一审查基线中的指标口径。",
            source_artifact_ids=[req.requirement_id],
            target_artifact_ids=[target_id],
            evidence_ids=[req.source_evidence_id, target_evidence_id],
            source_quote=f"{req.source_quote}\n{target_quote}",
        ))
    return review_items


def _detect_baseline_review_items(
    materials: list[MaterialItem],
    requirements: list[RequirementNode],
    design_items: list[DesignImplementationItem],
    verification_claims: list[VerificationClaim],
) -> list[CrossDocumentReviewItem]:
    review_items: list[CrossDocumentReviewItem] = []
    material_refs = [
        {
            "material": material,
            "baseline_id": (material.baseline_id or "").strip(),
            "document_version": (material.document_version or "").strip(),
        }
        for material in materials
        if material.included_in_formal_review
    ]

    baseline_values = sorted({item["baseline_id"] for item in material_refs if item["baseline_id"]})
    if len(baseline_values) > 1:
        quotes = [
            f"{item['material'].name}: role={item['material'].document_role or 'unassigned'}, baseline={item['baseline_id'] or '-'}, version={item['document_version'] or '-'}"
            for item in material_refs
        ]
        review_items.append(CrossDocumentReviewItem(
            review_item_id="p0-baseline_version_mismatch-1",
            item_type="baseline_version_mismatch",
            severity=_severity_for("baseline_version_mismatch"),
            title="版本基线不一致",
            description=f"正式审查材料中出现多个 baseline_id: {', '.join(baseline_values)}。",
            impact="基线不一致会削弱需求、设计、接口和验证之间的可追溯审查结论。",
            recommendation="明确本轮审查采用的正式基线；旧版本材料应标注为参考材料或补充说明。",
            source_artifact_ids=[item["material"].name for item in material_refs],
            evidence_ids=[f"material:{item['material'].name}" for item in material_refs],
            source_quote="\n".join(quotes),
        ))

    review_items.extend(_detect_inline_version_conflicts(requirements, design_items, verification_claims, start_index=len(review_items) + 1))
    return review_items


def _detect_inline_version_conflicts(
    requirements: list[RequirementNode],
    design_items: list[DesignImplementationItem],
    verification_claims: list[VerificationClaim],
    start_index: int,
) -> list[CrossDocumentReviewItem]:
    version_re = re.compile(r"\bV\d+(?:\.\d+)*\b", re.IGNORECASE)
    refs_by_family: dict[str, list[tuple[str, str, str, str]]] = defaultdict(list)
    artifacts = [*requirements, *design_items, *verification_claims]
    for artifact in artifacts:
        quote = getattr(artifact, "source_quote", "") or ""
        if not quote or not any(token in quote for token in ("版本", "基线", "引用", "version", "Version")):
            continue
        versions = [item.upper() for item in version_re.findall(quote)]
        if not versions:
            continue
        artifact_id = (
            getattr(artifact, "requirement_id", "")
            or getattr(artifact, "design_item_id", "")
            or getattr(artifact, "verification_id", "")
        )
        family = _version_family(quote)
        evidence_id = getattr(artifact, "source_evidence_id", "")
        for version in versions:
            refs_by_family[family].append((version, artifact_id, evidence_id, quote))

    items: list[CrossDocumentReviewItem] = []
    for family, refs in refs_by_family.items():
        versions = sorted({version for version, _, _, _ in refs})
        if len(versions) <= 1:
            continue
        items.append(CrossDocumentReviewItem(
            review_item_id=f"p0-baseline_version_mismatch-{start_index + len(items)}",
            item_type="baseline_version_mismatch",
            severity=_severity_for("baseline_version_mismatch"),
            title="版本基线不一致",
            description=f"{family} 相关证据中出现多个版本引用: {', '.join(versions)}。",
            impact="跨文档引用版本不一致时，不能直接形成稳定的闭环审查结论。",
            recommendation="复核引用版本，统一本轮评审基线，并说明旧版本证据的使用边界。",
            source_artifact_ids=[artifact_id for _, artifact_id, _, _ in refs if artifact_id],
            evidence_ids=[evidence_id for _, _, evidence_id, _ in refs if evidence_id],
            source_quote="\n".join(dict.fromkeys(quote for _, _, _, quote in refs if quote)),
        ))
    return items


def _metric_satisfies(comparator: str, target: float, observed: float) -> bool:
    if comparator in ("<=", "<"):
        return observed <= target if comparator == "<=" else observed < target
    if comparator in (">=", ">"):
        return observed >= target if comparator == ">=" else observed > target
    return abs(observed - target) < 1e-9


def _severity_for(item_type: str, override: str = "") -> str:
    return override or REVIEW_ITEM_DEFAULT_SEVERITY.get(item_type, "minor")


def _convert_value(value: float, source_unit: str, target_unit: str) -> float | None:
    source = normalize_unit(source_unit or "")
    target = normalize_unit(target_unit or "")
    if not source or not target:
        return None
    if source == target:
        return value
    return convert_value(value, source, target)


def _statistic_basis(text: str) -> str:
    sample = (text or "").lower()
    if any(token in sample for token in ("3σ", "3sigma", "three sigma", "三西格玛")):
        return "3σ"
    if "rms" in sample or "均方根" in sample:
        return "RMS"
    if "最大值" in text or "max" in sample or "峰值" in text:
        return "最大值"
    if "均值" in text or "平均值" in text or "mean" in sample:
        return "均值"
    return ""


def _impact_for(item_type: str) -> str:
    return {
        "missing_decomposition": "上级需求未形成可审查的下级技术需求，影响后续设计闭合和验证覆盖。",
        "missing_design_closure": "需求尚未闭合到设计实现项，不能直接判定设计方案满足该需求。",
        "design_item_without_requirement_basis": "设计依据链不完整，需要工程师确认需求来源或补充约束依据。",
        "missing_verification": "验证覆盖不足，不能形成该需求已验证通过的正式结论。",
    }.get(item_type, "")


def _evidence_for(
    artifact_id: str,
    requirements: list[RequirementNode],
    design_items: list[DesignImplementationItem],
    verification_claims: list[VerificationClaim],
) -> str:
    for item in requirements:
        if item.requirement_id == artifact_id:
            return item.source_evidence_id
    for item in design_items:
        if item.design_item_id == artifact_id:
            return item.source_evidence_id
    for item in verification_claims:
        if item.verification_id == artifact_id:
            return item.source_evidence_id
    return ""


def _version_family(text: str) -> str:
    lowered = text.lower()
    if "需求" in text or "req" in lowered:
        return "需求基线"
    if "设计" in text or "design" in lowered:
        return "设计基线"
    if "接口" in text or "icd" in lowered or "interface" in lowered:
        return "接口基线"
    if "仿真" in text or "simulation" in lowered:
        return "仿真基线"
    if "验证" in text or "verification" in lowered:
        return "验证基线"
    return "版本基线"
