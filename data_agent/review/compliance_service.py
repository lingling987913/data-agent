from __future__ import annotations

from typing import Any

from data_agent.review.cross_doc_service import run_cross_document_checks
from data_agent.review.evidence_mapper import map_check_items_to_evidence
from data_agent.review.material_classifier import classify_material
from data_agent.review.rule_extractor import extract_check_items
from data_agent.review.schemas import (
    PackageReviewReport,
    ParsedMaterial,
    ReviewPlusFinding,
    ReviewPlusJudgment,
    ReviewPlusMaterialRole,
)


def _compose_markdown(report: PackageReviewReport) -> str:
    lines = [
        "# 文档包审查报告",
        "",
        f"**场景**: {report.scenario}",
        f"**包 ID**: {report.package_id or '-'}",
        "",
        "## 1. 审查摘要",
        report.summary,
        "",
        "## 2. 检查项符合性审查",
        "",
    ]
    for finding in report.findings:
        lines.extend([
            f"### {finding.title}",
            f"- 判定: {finding.judgment.value}",
            f"- 说明: {finding.reasoning}",
            f"- 证据: {', '.join(finding.evidence_refs) or '无'}",
            "",
        ])

    lines.extend(["## 3. 多文档一致性审查", ""])
    if not report.cross_doc_findings:
        lines.append("未发现显著跨文档一致性问题（基于关键词启发式检测）。")
    else:
        for item in report.cross_doc_findings:
            lines.extend([
                f"### {item.title}",
                f"- 严重度: {item.severity}",
                f"- 描述: {item.description}",
                f"- 文档: {item.doc_a} ↔ {item.doc_b}",
                "",
            ])

    lines.extend(["## 4. 审查结论", "", report.conclusion])
    return "\n".join(lines)


def run_package_review(
    materials: list[ParsedMaterial],
    *,
    scenario: str,
    package_id: str | None,
    evidence_pools: dict[str, list[dict[str, Any]]],
) -> PackageReviewReport:
    # 角色分类（覆盖简单规则）
    for material in materials:
        role, confidence, reason = classify_material(
            material.name,
            material.content,
            material.file_path,
        )
        material.role = role
        material.role_confidence = confidence
        material.role_reason = reason

    # 从 review_rule xlsx 或 checklist docx 抽取检查项
    check_items = []
    for material in materials:
        if material.role in {
            ReviewPlusMaterialRole.REVIEW_RULE,
            ReviewPlusMaterialRole.CHECKLIST,
        }:
            items = extract_check_items(
                material.file_path,
                material.name,
                material.content,
            )
            check_items.extend(items)

    findings = map_check_items_to_evidence(check_items, evidence_pools)
    cross_doc = run_cross_document_checks(materials)

    satisfied = sum(1 for f in findings if f.judgment == ReviewPlusJudgment.SATISFIED)
    insufficient = sum(1 for f in findings if f.judgment == ReviewPlusJudgment.INSUFFICIENT_EVIDENCE)
    not_satisfied = sum(1 for f in findings if f.judgment == ReviewPlusJudgment.NOT_SATISFIED)
    critical = sum(1 for f in findings if f.severity == "critical") + sum(
        1 for c in cross_doc if c.severity == "critical"
    )

    if insufficient > 0 or cross_doc or not_satisfied > 0:
        conclusion = (
            f"共 {len(check_items)} 条检查项：满足 {satisfied} 条，证据不足 {insufficient} 条，"
            f"不满足 {not_satisfied} 条；跨文档问题 {len(cross_doc)} 条。建议补充证据后复核。"
        )
    elif satisfied == len(check_items) and check_items:
        conclusion = "所有检查项均找到相关证据，但未替代人工正式审查。"
    else:
        conclusion = "检查项为空或未能完成有效审查。"

    report = PackageReviewReport(
        scenario=scenario,
        package_id=package_id,
        check_items=check_items,
        total_check_items=len(check_items),
        satisfied_count=satisfied,
        insufficient_evidence_count=insufficient,
        not_satisfied_count=not_satisfied,
        critical_count=critical,
        findings=findings,
        cross_doc_findings=cross_doc,
        conclusion=conclusion,
        summary=(
            f"材料 {len(materials)} 份，检查项 {len(check_items)} 条，"
            f"符合性发现 {len(findings)} 条，跨文档发现 {len(cross_doc)} 条。"
        ),
    )
    report.markdown = _compose_markdown(report)
    return report
