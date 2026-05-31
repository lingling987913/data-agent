from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from data_agent.review_workbench.issue_taxonomy import (
    build_conclusion_payload,
    classify_finding,
    count_problem_buckets,
    localize_conclusion_text,
    localize_report_markdown,
    resolve_judgment_label_zh,
    resolve_severity_label_zh,
    resolve_verdict_label_zh,
    resolve_work_item_status_label_zh,
    summarize_judgment_stats,
)
from data_agent.super_agent.smart_diagnostics import filter_business_degradation


ReviewType = Literal["super_agent", "review_plus", "gnc_review", "hybrid"]
ReportAudience = Literal["internal", "user"]

_REVIEW_STATUS_LABELS: dict[str, str] = {
    "completed": "已完成",
    "limited": "部分完成",
    "failed": "未完整完成",
    "running": "进行中",
    "pending": "待处理",
    "blocked": "已阻断",
    "parsed": "已解析",
    "ready": "可审查",
}

_USER_SECTION_LABELS: dict[str, str] = {
    "Review-Plus": "文件组审查",
    "GNC Review": "专业审查",
    "审查结果": "审查结果",
}

_INTERNAL_REPORT_MARKERS: tuple[str, ...] = (
    "Report ID:",
    "Review type:",
    "Generated at:",
    "## 2. 解析与结构化质量",
    "## 3. 结构化解析结果",
    "Layout blocks:",
    "Source block:",
    "Finding ID:",
    "## 附录 A：解析产物摘要",
    "## 附录 B：原始结构化数据索引",
    "Super Agent 统一审查报告",
    "GNC 统一审查报告",
)


def is_internal_review_report(markdown: str) -> bool:
    """Return True when markdown looks like an engineering/internal trace report."""
    text = str(markdown or "")
    if not text.strip():
        return False
    hits = sum(1 for marker in _INTERNAL_REPORT_MARKERS if marker in text)
    return hits >= 2


class ReviewReportInput(BaseModel):
    report_id: str
    review_type: ReviewType = "super_agent"
    audience: ReportAudience = "internal"
    structured_bundle: dict[str, Any] = Field(default_factory=dict)
    parse_artifact: dict[str, Any] = Field(default_factory=dict)
    review_results: dict[str, Any] = Field(default_factory=dict)
    quality_report: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ReviewReportArtifact(BaseModel):
    report_id: str
    title: str
    markdown: str
    review_index: dict[str, Any] = Field(default_factory=dict)
    render_blocks: list[dict[str, Any]] = Field(default_factory=list)
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    source_parse_artifact_id: str = ""
    source_review_ids: list[str] = Field(default_factory=list)


def _as_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if hasattr(value, "dict"):
        return value.dict()
    return {}


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    return []


def _clip(value: Any, limit: int = 320) -> str:
    text = str(value or "").strip().replace("\r\n", "\n")
    return text if len(text) <= limit else text[: limit - 1] + "..."


def _anchor(raw: str, prefix: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_.:-]+", "-", str(raw or "").strip()).strip("-")
    return f"{prefix}-{text or 'unknown'}"


def _escape_cell(value: Any) -> str:
    return str(value or "").replace("\n", "<br>").replace("|", "\\|")


def _json_inline(value: Any, limit: int = 240) -> str:
    if value in (None, "", [], {}):
        return ""
    return _clip(json.dumps(value, ensure_ascii=False), limit)


def _structured_bundle(data: ReviewReportInput) -> dict[str, Any]:
    return data.structured_bundle or data.parse_artifact.get("structured_bundle") or data.parse_artifact


def _review_sections(review_results: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    sections: list[tuple[str, dict[str, Any]]] = []
    if review_results.get("review_plus_result"):
        sections.append(("Review-Plus", _as_dict(review_results.get("review_plus_result"))))
    if review_results.get("gnc_review_result"):
        sections.append(("GNC Review", _as_dict(review_results.get("gnc_review_result"))))
    if not sections and review_results:
        sections.append(("审查结果", review_results))
    return sections


def _extract_findings(review_results: dict[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for _, section in _review_sections(review_results):
        report = _as_dict(section.get("report"))
        findings.extend(_as_list(section.get("findings")))
        findings.extend(_as_list(section.get("cross_doc_findings")))
        findings.extend(_as_list(section.get("cross_document_items")))
        findings.extend(_as_list(report.get("findings")))
        findings.extend(_as_list(report.get("cross_document_items")))
        for specialist_review in _as_list(section.get("specialist_reviews")):
            findings.extend(_as_list(_as_dict(specialist_review).get("findings")))

    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(findings, start=1):
        finding = _as_dict(item)
        if not finding:
            continue
        key = str(
            finding.get("finding_id")
            or finding.get("review_item_id")
            or finding.get("check_item_id")
            or f"{finding.get('title', '')}|{finding.get('description', '')}|{index}"
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(finding)
    return deduped


def _review_status_label(status: Any) -> str:
    key = str(status or "completed").strip().lower()
    return _REVIEW_STATUS_LABELS.get(key, "已完成" if key in {"", "success", "done"} else key)


def _display_conclusion_text(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    localized = localize_conclusion_text(text)
    if localized != text:
        return localized
    return text


def _resolve_check_item_stats(
    findings: list[dict[str, Any]],
    review_results: dict[str, Any],
    bundle: dict[str, Any],
) -> dict[str, int]:
    for _, section in _review_sections(review_results):
        report = _as_dict(section.get("report"))
        total = int(report.get("total_check_items") or 0)
        if total > 0:
            return {
                "total": total,
                "satisfied": int(report.get("satisfied_count") or 0),
                "not_satisfied": int(report.get("not_satisfied_count") or 0),
                "insufficient": int(report.get("insufficient_evidence_count") or 0),
                "not_checked": int(report.get("not_checked_count") or 0),
            }

    stats = _as_dict(bundle.get("stats"))
    total_hint = int(stats.get("check_item_count") or 0)
    return summarize_judgment_stats(findings, total_check_items=total_hint)


def _review_conclusion(section: dict[str, Any]) -> str:
    report = _as_dict(section.get("report"))
    if section.get("review_mode") == "smart_committee":
        specialist_reviews = _as_list(section.get("specialist_reviews"))
        finding_count = section.get("finding_count")
        if finding_count in (None, ""):
            finding_count = sum(len(_as_list(_as_dict(item).get("findings"))) for item in specialist_reviews)
        if specialist_reviews or finding_count:
            return _clip(
                _display_conclusion_text(section.get("review_conclusion"))
                or _display_conclusion_text(section.get("conclusion"))
                or (
                    f"智能专家委员会完成 {len(specialist_reviews)} 项专业审查，"
                    f"共形成 {int(finding_count or 0)} 条审查发现；"
                    f"当前状态：{_review_status_label(section.get('status'))}。"
                ),
                500,
            )
    verdict = _as_dict(section.get("chief_decision")).get("verdict")
    return _clip(
        _display_conclusion_text(section.get("review_conclusion"))
        or _display_conclusion_text(section.get("conclusion"))
        or _display_conclusion_text(report.get("conclusion"))
        or resolve_verdict_label_zh(str(verdict or "")),
        500,
    )


def _extract_evidences(bundle: dict[str, Any], review_results: dict[str, Any]) -> list[dict[str, Any]]:
    pool = _as_dict(bundle.get("evidence_pool"))
    evidences = _as_list(pool.get("evidences"))
    for _, section in _review_sections(review_results):
        evidences.extend(_as_list(section.get("evidence")))
        evidences.extend(_as_list(section.get("evidences")))
    dedup: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(evidences, start=1):
        ev = _as_dict(item)
        ev_id = str(ev.get("evidence_id") or ev.get("id") or f"evidence-{index}")
        ev.setdefault("evidence_id", ev_id)
        dedup.setdefault(ev_id, ev)
    return list(dedup.values())


def _document_ir(bundle: dict[str, Any]) -> dict[str, Any]:
    return _as_dict(bundle.get("document_ir"))


def _material_rows(bundle: dict[str, Any]) -> list[str]:
    materials = _as_list(bundle.get("materials"))
    rows = ["| 文件 | 类型/角色 | 解析器 | 状态 |", "| --- | --- | --- | --- |"]
    if not materials:
        return ["- 未返回逐文件材料清单。"]
    for item in materials:
        mat = _as_dict(item)
        rows.append(
            "| {name} | {kind} | {parser} | {status} |".format(
                name=_escape_cell(mat.get("name") or mat.get("file_name")),
                kind=_escape_cell(mat.get("file_type") or mat.get("role")),
                parser=_escape_cell(mat.get("parser_name") or mat.get("parser_type")),
                status=_escape_cell(mat.get("parse_status") or mat.get("status")),
            )
        )
    return rows


def _quality_lines(bundle: dict[str, Any], quality: dict[str, Any]) -> list[str]:
    stats = _as_dict(bundle.get("stats"))
    warnings = filter_business_degradation(
        [str(item) for item in _as_list(bundle.get("warnings")) + _as_list(quality.get("warnings"))]
    )
    lines = [
        f"- 文档数: {stats.get('document_count', len(_as_list(bundle.get('materials'))))}",
        f"- 章节数: {stats.get('section_count', 0)}",
        f"- 证据数: {stats.get('evidence_count', 0)}",
        f"- Layout blocks: {stats.get('layout_block_count', 0)}",
        f"- 表格: {stats.get('table_element_count', 0)}",
        f"- 图片/视觉元素: {stats.get('visual_element_count', 0)}",
        f"- 流程/框图: {stats.get('graph_element_count', 0)}",
        f"- 图表: {stats.get('chart_element_count', 0)}",
        f"- 解析质量分: {quality.get('parse_quality_score', 'n/a')}",
        f"- 证据质量分: {quality.get('evidence_quality_score', 'n/a')}",
        f"- 需人工确认: {bool(quality.get('human_confirmation_required') or warnings)}",
    ]
    if warnings:
        lines.extend(["", "### 2.1 降级与告警", ""])
        lines.extend(f"- {warning}" for warning in warnings[:30])
    return lines


def _formula_elements(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    formulas: list[dict[str, Any]] = []
    for chunk in _as_list(bundle.get("chunks")):
        block = _as_dict(chunk)
        if block.get("formula_latex") or block.get("block_type") == "formula":
            formulas.append(block)
    for block in _as_list(_document_ir(bundle).get("layout_blocks")):
        item = _as_dict(block)
        metadata = _as_dict(item.get("metadata"))
        if item.get("block_type") == "formula" or metadata.get("formula_latex"):
            formulas.append(item)
    return formulas


def _render_table_elements(ir: dict[str, Any], index: dict[str, Any]) -> list[str]:
    tables = [_as_dict(item) for item in _as_list(ir.get("table_elements"))]
    if not tables:
        return ["- 未识别到结构化表格。"]
    lines: list[str] = []
    for table in tables[:20]:
        table_id = str(table.get("table_id") or table.get("id") or "table")
        anchor_id = _anchor(table_id, "table")
        index["structured_elements"].append(
            {
                "element_id": table_id,
                "anchor_id": anchor_id,
                "element_type": "table",
                "source_file_name": table.get("source_file_name", ""),
                "confidence": table.get("confidence", 0.0),
            }
        )
        lines.extend(
            [
                f'<a id="{anchor_id}"></a>',
                f"#### 表格 {table_id}",
                f"- 来源: {table.get('source_file_name', '')}",
                f"- Source block: {table.get('source_block_id', '')}",
                f"- Confidence: {table.get('confidence', 0.0)}",
                "",
                str(table.get("markdown") or "未返回 Markdown 表格内容。"),
                "",
            ]
        )
    return lines


def _render_visual_elements(ir: dict[str, Any], index: dict[str, Any], human_items: list[str]) -> list[str]:
    visuals = [_as_dict(item) for item in _as_list(ir.get("visual_elements"))]
    if not visuals:
        return ["- 未识别到图片/视觉元素。"]
    lines: list[str] = []
    for visual in visuals[:30]:
        visual_id = str(visual.get("visual_id") or "visual")
        anchor_id = _anchor(visual_id, "visual")
        requires = bool(visual.get("requires_human_confirmation"))
        if requires:
            human_items.append(f"视觉元素 {visual_id} 需要人工复核，confidence={visual.get('confidence', 0.0)}")
        index["structured_elements"].append(
            {
                "element_id": visual_id,
                "anchor_id": anchor_id,
                "element_type": "visual",
                "source_file_name": visual.get("source_file_name", ""),
                "confidence": visual.get("confidence", 0.0),
            }
        )
        lines.extend(
            [
                f'<a id="{anchor_id}"></a>',
                f"- **{visual_id}** ({visual.get('visual_type', 'figure')}): {_clip(visual.get('description'), 180)}",
                f"  - 来源: {visual.get('source_file_name', '')}; confidence={visual.get('confidence', 0.0)}; requires_human_confirmation={requires}",
            ]
        )
    return lines


def _render_graph_elements(ir: dict[str, Any], index: dict[str, Any], human_items: list[str]) -> list[str]:
    graphs = [_as_dict(item) for item in _as_list(ir.get("graph_elements"))]
    if not graphs:
        return ["- 未识别到流程图/框图结构。"]
    lines: list[str] = []
    for graph in graphs[:20]:
        graph_id = str(graph.get("graph_id") or "graph")
        anchor_id = _anchor(graph_id, "graph")
        nodes = _as_list(graph.get("nodes"))
        edges = _as_list(graph.get("edges"))
        index["structured_elements"].append(
            {
                "element_id": graph_id,
                "anchor_id": anchor_id,
                "element_type": "graph",
                "source_file_name": graph.get("source_file_name", ""),
                "confidence": graph.get("confidence", 0.0),
            }
        )
        lines.extend([f'<a id="{anchor_id}"></a>', f"#### 流程/框图 {graph_id}"])
        if nodes and edges:
            lines.extend(["```mermaid", "flowchart TD"])
            for node in nodes[:50]:
                n = _as_dict(node)
                node_id = re.sub(r"[^A-Za-z0-9_]+", "_", str(n.get("id") or n.get("name") or "node"))
                lines.append(f'  {node_id}["{_clip(n.get("label") or n.get("name") or node_id, 80)}"]')
            for edge in edges[:80]:
                e = _as_dict(edge)
                src = re.sub(r"[^A-Za-z0-9_]+", "_", str(e.get("source") or e.get("from") or ""))
                dst = re.sub(r"[^A-Za-z0-9_]+", "_", str(e.get("target") or e.get("to") or ""))
                if src and dst:
                    label = _clip(e.get("label"), 40)
                    lines.append(f"  {src} -->|{label}| {dst}" if label else f"  {src} --> {dst}")
            lines.append("```")
        else:
            reason = graph.get("unparsed_reason") or "nodes/edges 未恢复"
            human_items.append(f"流程/框图 {graph_id} 未形成可复核拓扑: {reason}")
            lines.append(f"- 低置信结构摘要: confidence={graph.get('confidence', 0.0)}; unparsed_reason={reason}")
        lines.append("")
    return lines


def _render_chart_elements(ir: dict[str, Any], index: dict[str, Any], human_items: list[str]) -> list[str]:
    charts = [_as_dict(item) for item in _as_list(ir.get("chart_elements"))]
    if not charts:
        return ["- 未识别到复杂图表结构。"]
    lines: list[str] = []
    for chart in charts[:20]:
        chart_id = str(chart.get("chart_id") or "chart")
        anchor_id = _anchor(chart_id, "chart")
        if chart.get("unparsed_reason"):
            human_items.append(f"图表 {chart_id} 需要人工复核: {chart.get('unparsed_reason')}")
        index["structured_elements"].append(
            {
                "element_id": chart_id,
                "anchor_id": anchor_id,
                "element_type": "chart",
                "source_file_name": chart.get("source_file_name", ""),
                "confidence": chart.get("confidence", 0.0),
            }
        )
        lines.extend(
            [
                f'<a id="{anchor_id}"></a>',
                f"- **{chart_id}**: type={chart.get('chart_type', 'unknown')}; confidence={chart.get('confidence', 0.0)}",
                f"  - axes: {_json_inline(chart.get('axes'))}",
                f"  - series: {_json_inline(chart.get('series'))}",
                f"  - unparsed_reason: {chart.get('unparsed_reason', '')}",
            ]
        )
    return lines


def _render_formula_elements(bundle: dict[str, Any], index: dict[str, Any]) -> list[str]:
    formulas = _formula_elements(bundle)
    if not formulas:
        return ["- 未识别到独立公式块。"]
    lines: list[str] = []
    for index_no, formula in enumerate(formulas[:30], start=1):
        formula_id = str(formula.get("block_id") or formula.get("source_block_id") or f"formula-{index_no}")
        anchor_id = _anchor(formula_id, "formula")
        text = formula.get("formula_latex") or _as_dict(formula.get("metadata")).get("formula_latex") or formula.get("text")
        index["structured_elements"].append(
            {
                "element_id": formula_id,
                "anchor_id": anchor_id,
                "element_type": "formula",
                "source_file_name": formula.get("source_file_name", ""),
                "confidence": formula.get("confidence", 0.0),
            }
        )
        lines.extend([f'<a id="{anchor_id}"></a>', f"#### 公式 {formula_id}", "", f"$$\n{text}\n$$", ""])
    return lines


def _render_layout_summary(ir: dict[str, Any]) -> list[str]:
    blocks = [_as_dict(item) for item in _as_list(ir.get("layout_blocks"))]
    bbox_count = sum(1 for item in blocks if item.get("bbox"))
    low_conf = sum(1 for item in blocks if item.get("confidence") is not None and float(item.get("confidence") or 0) < 0.5)
    parsers = sorted({str(item.get("parser_name")) for item in blocks if item.get("parser_name")})
    return [
        f"- Pages/slides: {len(_as_list(ir.get('pages')))}",
        f"- Layout blocks: {len(blocks)}",
        f"- BBox coverage: {bbox_count}/{len(blocks)}",
        f"- Low confidence blocks: {low_conf}",
        f"- Parsers: {', '.join(parsers) if parsers else 'n/a'}",
    ]


def _finding_ids(finding: dict[str, Any], index_no: int) -> tuple[str, str]:
    finding_id = str(
        finding.get("finding_id")
        or finding.get("review_item_id")
        or finding.get("id")
        or finding.get("check_item_id")
        or f"FND-{index_no:03d}"
    )
    return finding_id, _anchor(finding_id, "finding")


def _render_findings(findings: list[dict[str, Any]], index: dict[str, Any], human_items: list[str]) -> list[str]:
    if not findings:
        return ["- 未返回审查 findings。"]
    lines: list[str] = []
    for index_no, finding in enumerate(findings[:80], start=1):
        finding_id, anchor_id = _finding_ids(finding, index_no)
        evidence_ids = _as_list(finding.get("evidence_ids") or finding.get("evidence_refs"))
        standard_ids = _as_list(finding.get("rule_ids") or finding.get("standard_ids"))
        confidence = float(finding.get("confidence") or 0.0)
        if finding.get("requires_human_confirmation") or confidence < 0.5:
            human_items.append(f"Finding {finding_id} 需要人工复核，confidence={confidence}")
        index["findings"].append(
            {
                "finding_id": finding_id,
                "anchor_id": anchor_id,
                "evidence_ids": evidence_ids,
                "standard_ids": standard_ids,
                "structured_element_ids": _as_list(finding.get("structured_element_ids")),
                "review_status": finding.get("review_status") or "pending",
            }
        )
        lines.extend(
            [
                f'<a id="{anchor_id}"></a>',
                f"### {index_no}. [{finding.get('severity', '')}] {finding.get('title', finding_id)}",
                f"- Finding ID: `{finding_id}`",
                f"- Judgment: {finding.get('judgment', '')}",
                f"- Confidence: {confidence}",
                f"- Evidence: {', '.join(map(str, evidence_ids)) or '未关联'}",
                f"- Standard: {', '.join(map(str, standard_ids)) or '未关联'}",
                f"- Description: {_clip(finding.get('description') or finding.get('reasoning'), 800)}",
                f"- Recommendation: {_clip(finding.get('recommendation'), 500)}",
                "",
            ]
        )
    return lines


def _judgment_label(value: Any) -> str:
    key = str(value or "").strip()
    if not key:
        return "未检查"
    return resolve_judgment_label_zh(key) or "未检查"


def _user_material_rows(bundle: dict[str, Any]) -> list[str]:
    materials = _as_list(bundle.get("materials"))
    rows = ["| 序号 | 文件名称 | 材料角色 | 说明 |", "| --- | --- | --- | --- |"]
    if not materials:
        return ["- 未提供送审材料清单。"]
    for index, item in enumerate(materials, start=1):
        mat = _as_dict(item)
        rows.append(
            "| {index} | {name} | {role} | {note} |".format(
                index=index,
                name=_escape_cell(mat.get("name") or mat.get("file_name")),
                role=_escape_cell(mat.get("role") or mat.get("file_type")),
                note=_escape_cell(mat.get("description") or mat.get("summary") or "—"),
            )
        )
    return rows


def _user_finding_location(finding: dict[str, Any]) -> str:
    parts = [
        str(finding.get("source_material_name") or finding.get("source_file_name") or "").strip(),
        str(finding.get("source_sheet") or finding.get("section_title") or finding.get("section_id") or "").strip(),
    ]
    if finding.get("source_row"):
        parts.append(f"第 {finding.get('source_row')} 行")
    if finding.get("page_no"):
        parts.append(f"第 {finding.get('page_no')} 页")
    location = " / ".join(part for part in parts if part)
    quote = str(finding.get("source_quote") or finding.get("excerpt") or "").strip()
    if quote and location:
        return f"{location}：{_clip(quote, 180)}"
    return quote or location or "—"


def _user_checklist_rows(findings: list[dict[str, Any]]) -> list[str]:
    if not findings:
        return ["- 未形成可归档的检查项判定。"]
    rows = [
        "| 序号 | 检查项 | 检查对象 | 检查要求 | 结论 | 证据/位置 | 备注 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for index, finding in enumerate(findings[:120], start=1):
        title = finding.get("title") or f"检查项 {index}"
        check_object = (
            finding.get("check_object")
            or finding.get("source_material_name")
            or finding.get("source_file_name")
            or finding.get("discipline")
            or "—"
        )
        requirement = (
            finding.get("requirement_text")
            or finding.get("acceptance_criteria")
            or finding.get("description")
            or "—"
        )
        rows.append(
            "| {index} | {title} | {check_object} | {requirement} | {judgment} | {location} | {notes} |".format(
                index=index,
                title=_escape_cell(title),
                check_object=_escape_cell(_clip(check_object, 120)),
                requirement=_escape_cell(_clip(requirement, 240)),
                judgment=_escape_cell(_judgment_label(finding.get("judgment"))),
                location=_escape_cell(_clip(_user_finding_location(finding), 240)),
                notes=_escape_cell(_clip(finding.get("recommendation"), 240) or "—"),
            )
        )
    return rows


def _user_cross_document_rows(review_results: dict[str, Any]) -> list[str]:
    items: list[dict[str, Any]] = []
    for _, section in _review_sections(review_results):
        items.extend(_as_list(section.get("cross_doc_findings")))
        items.extend(_as_list(section.get("cross_document_items")))
        report = _as_dict(section.get("report"))
        items.extend(_as_list(report.get("cross_document_items")))
    if not items:
        return ["- 未发现需记录的跨文档一致性问题。"]
    rows = ["| 序号 | 问题描述 | 严重度 | 闭环建议 |", "| --- | --- | --- | --- |"]
    for index, item in enumerate(items[:40], start=1):
        row = _as_dict(item)
        rows.append(
            "| {index} | {description} | {severity} | {recommendation} |".format(
                index=index,
                description=_escape_cell(_clip(row.get("title") or row.get("description"), 280)),
                severity=_escape_cell(
                    resolve_severity_label_zh(str(row.get("severity") or "")) or "—"
                ),
                recommendation=_escape_cell(_clip(row.get("recommendation"), 240) or "—"),
            )
        )
    return rows


def _user_signature_block() -> list[str]:
    return [
        "| 角色 | 签署/确认 | 日期 | 备注 |",
        "| --- | --- | --- | --- |",
        "| 送审负责人 |  |  | 确认送审包与材料角色 |",
        "| 审查负责人 |  |  | 确认符合性审查结论 |",
        "| 质量/归档 |  |  | 确认归档与问题闭环 |",
    ]


_OFFICIAL_FINDING_CATEGORIES: tuple[tuple[str, str], ...] = (
    ("critical", "重大问题"),
    ("major", "主要问题"),
    ("minor", "一般问题"),
    ("suggestion", "建议项"),
    ("pending_expert", "待专家确认项"),
)

_DESIGN_ELEMENT_CATEGORY_HINTS: tuple[tuple[str, str], ...] = (
    ("姿态确定", "姿态确定"),
    ("定姿", "姿态确定"),
    ("姿态控制", "姿态控制"),
    ("控制律", "控制律"),
    ("执行机构", "执行机构"),
    ("推力器", "执行机构"),
    ("飞轮", "执行机构"),
    ("传感器", "传感器"),
    ("星敏", "传感器"),
    ("陀螺", "传感器"),
    ("参数", "参数"),
    ("验证", "验证项"),
    ("仿真", "验证项"),
)

_DEFAULT_REPORT_TITLE = "GNC 设计文档审查报告"


def _extract_report_verdict(review_results: dict[str, Any], metadata: dict[str, Any]) -> str:
    verdict = str(metadata.get("verdict") or "").strip()
    if verdict:
        return verdict
    for _, section in _review_sections(review_results):
        chief = _as_dict(section.get("chief_decision"))
        if chief.get("verdict"):
            return str(chief["verdict"])
        report = _as_dict(section.get("report"))
        chief_review = _as_dict(report.get("chief_comprehensive_review"))
        if chief_review.get("release_recommendation"):
            return str(chief_review["release_recommendation"])
    return ""


def _resolve_review_mode(review_type: ReviewType) -> str:
    if review_type == "gnc_review":
        return "gnc"
    if review_type == "review_plus":
        return "review_plus"
    if review_type == "hybrid":
        return "super_agent"
    return "generic"


def _gnc_section(review_results: dict[str, Any]) -> dict[str, Any]:
    return _as_dict(review_results.get("gnc_review_result"))


def _review_context(data: ReviewReportInput, review_results: dict[str, Any]) -> dict[str, str]:
    gnc = _gnc_section(review_results)
    gnc_meta = _as_dict(gnc.get("metadata"))
    return {
        "product_model": str(
            data.metadata.get("product_model")
            or gnc_meta.get("product_model")
            or data.metadata.get("model")
            or "—"
        ),
        "review_phase": str(
            data.metadata.get("review_phase")
            or gnc_meta.get("review_phase")
            or "CDR"
        ),
        "review_scope": str(
            data.metadata.get("review_scope")
            or gnc_meta.get("review_scope")
            or data.metadata.get("objective")
            or "—"
        ),
    }


def _template_gatekeeping_rows(quality: dict[str, Any], bundle: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for source in (
        _as_list(quality.get("template_gatekeeping")),
        _as_list(bundle.get("template_gatekeeping")),
        _as_list(_as_dict(bundle.get("quality_screening")).get("template_gatekeeping")),
    ):
        for item in source:
            row = _as_dict(item)
            if row:
                rows.append(row)
    return rows


def _official_finding_category(finding: dict[str, Any], *, review_mode: str) -> str:
    judgment = str(finding.get("judgment") or finding.get("status") or "").strip().lower()
    if finding.get("requires_human_confirmation") or judgment in {"not_checked", "blocked"}:
        return "pending_expert"
    bucket, _ = classify_finding(finding, review_mode=review_mode)  # type: ignore[arg-type]
    if bucket in {"manual_review", "insufficient_evidence"}:
        return "pending_expert"
    severity = str(finding.get("severity") or "").strip().lower()
    if severity in {"critical", "blocker"} or bucket == "severe_error":
        return "critical"
    if severity in {"info", "suggestion", "low"} and judgment not in {"not_satisfied", "failed"}:
        return "suggestion"
    if severity in {"minor", "medium"} and bucket not in {
        "content_nonconforming",
        "cross_document_inconsistency",
        "template_structure_nonconforming",
    }:
        return "minor"
    if severity in {"major", "high"} or bucket in {
        "content_nonconforming",
        "cross_document_inconsistency",
        "template_structure_nonconforming",
    }:
        return "major"
    if judgment in {"not_satisfied", "failed", "non_compliant", "nonconforming"}:
        return "major"
    if judgment == "insufficient_evidence":
        return "pending_expert"
    return "minor"


def _group_findings_by_official_category(
    findings: list[dict[str, Any]],
    *,
    review_mode: str,
) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {key: [] for key, _ in _OFFICIAL_FINDING_CATEGORIES}
    for finding in findings:
        if not finding:
            continue
        category = _official_finding_category(finding, review_mode=review_mode)
        grouped.setdefault(category, []).append(finding)
    return grouped


def _finding_discipline_label(finding: dict[str, Any]) -> str:
    for key in ("discipline", "expert_role", "agent_id", "category"):
        value = str(finding.get(key) or "").strip()
        if value and not value.replace("_", "").isascii():
            return value
        if value and "_" not in value:
            return value
    return "—"


def _render_official_finding_entries(findings: list[dict[str, Any]], *, start_index: int = 1) -> list[str]:
    if not findings:
        return ["- 本类别暂无记录项。"]
    lines: list[str] = []
    for offset, finding in enumerate(findings[:40], start=start_index):
        lines.extend(
            [
                f"#### {offset}. {_clip(finding.get('title') or finding.get('description') or '审查发现', 120)}",
                f"- 专业领域：{_finding_discipline_label(finding)}",
                f"- 问题类型：{resolve_judgment_label_zh(str(finding.get('judgment') or '')) or '—'}",
                f"- 问题描述：{_clip(finding.get('description') or finding.get('reasoning'), 600)}",
                f"- 整改建议：{_clip(finding.get('recommendation'), 400) or '—'}",
                f"- 证据定位：{_clip(_user_finding_location(finding), 400)}",
                "",
            ]
        )
    return lines


def _material_quality_lines(
    bundle: dict[str, Any],
    quality: dict[str, Any],
    review_results: dict[str, Any],
) -> list[str]:
    stats = _as_dict(bundle.get("stats"))
    warnings = filter_business_degradation(
        [str(item) for item in _as_list(bundle.get("warnings")) + _as_list(quality.get("warnings"))]
    )
    template_rows = _template_gatekeeping_rows(quality, bundle)
    hard_fails = [row for row in template_rows if str(row.get("status") or "").lower() == "hard_fail"]
    soft_fails = [row for row in template_rows if str(row.get("status") or "").lower() == "soft_fail"]
    package = _as_dict(quality.get("package_gatekeeping"))
    missing_items = _as_list(quality.get("missing_items")) or _as_list(package.get("missing_materials"))
    reviewable = quality.get("is_reviewable")
    if reviewable is None:
        reviewable = package.get("can_start_review", True)
    gnc = _gnc_section(review_results)
    gate_summary = str(
        package.get("gate_summary")
        or quality.get("gate_summary")
        or ("可开展审查" if reviewable else "材料不齐套或不可审")
    )

    lines = [
        "### 3.1 章节完整性",
        f"- 识别章节数：{stats.get('section_count', '—')}",
        f"- 模板 hard 缺项：{len(hard_fails)} 项",
        f"- 模板 soft 提示：{len(soft_fails)} 项",
    ]
    if hard_fails:
        lines.append("- 主要缺项章节：")
        for row in hard_fails[:12]:
            unit = str(row.get("unit_key") or row.get("unit_id") or row.get("title") or "模板单元")
            missing = _as_list(row.get("missing_sections") or row.get("missing_required_sections"))
            hint = f"（缺：{'、'.join(str(item) for item in missing[:3])}）" if missing else ""
            lines.append(f"  - {unit}{hint}")
    elif template_rows:
        lines.append("- 对照模板未发现 hard 级章节缺项。")
    else:
        lines.append("- 未返回模板章节门控结果，请结合正文目录人工复核。")

    lines.extend(
        [
            "",
            "### 3.2 材料可审性",
            f"- 判定结论：{gate_summary}",
            f"- 送审材料数：{stats.get('document_count', len(_as_list(bundle.get('materials'))))}",
            f"- 缺项材料：{'；'.join(str(item) for item in missing_items[:8]) or '无'}",
            f"- 结构化证据数：{stats.get('evidence_count', 0)}",
            "",
            "### 3.3 异常与缺陷提示",
        ]
    )
    if warnings:
        lines.extend(f"- {warning}" for warning in warnings[:20])
    else:
        lines.append("- 未发现需单独提示的解析降级或材料异常。")
    if gnc.get("status") == "failed":
        lines.append("- 审查流程未完整完成，以下结论仅供辅助参考。")
    return lines


def _infer_design_element_category(name: str, element_type: str = "") -> str:
    blob = f"{name} {element_type}".strip()
    for hint, label in _DESIGN_ELEMENT_CATEGORY_HINTS:
        if hint in blob:
            return label
    normalized = str(element_type or "").strip().lower()
    mapping = {
        "attitude_determination": "姿态确定",
        "attitude_control": "姿态控制",
        "actuator": "执行机构",
        "sensor": "传感器",
        "control_law": "控制律",
        "parameter": "参数",
        "verification": "验证项",
    }
    return mapping.get(normalized, element_type or "其他设计要素")


def _design_element_rows(bundle: dict[str, Any], findings: list[dict[str, Any]]) -> list[str]:
    rows = ["| 序号 | 设计要素类别 | 名称/指标 | 来源章节 | 说明 |", "| --- | --- | --- | --- | --- |"]
    items: list[tuple[str, str, str, str]] = []
    for element in _as_list(bundle.get("design_elements")):
        row = _as_dict(element)
        if not row:
            continue
        name = str(row.get("name") or row.get("normalized_name") or "").strip()
        if not name:
            continue
        items.append(
            (
                _infer_design_element_category(name, str(row.get("design_type") or "")),
                name,
                str(row.get("source_section_id") or row.get("source_text") or "—"),
                _clip(row.get("source_text") or row.get("description") or "—", 120),
            )
        )
    for param in _as_list(bundle.get("extracted_parameters")):
        row = _as_dict(param)
        if not row:
            continue
        name = str(row.get("name") or row.get("normalized_name") or row.get("raw_value") or "").strip()
        if not name:
            continue
        value = row.get("raw_value") or row.get("value")
        unit = str(row.get("unit") or "").strip()
        metric = f"{value}{unit}" if value not in (None, "") else name
        items.append(
            (
                _infer_design_element_category(name, "parameter"),
                name,
                str(row.get("source_section_id") or "—"),
                _clip(metric, 120),
            )
        )
    if not items:
        disciplines = sorted(
            {
                label
                for label in (_finding_discipline_label(item) for item in findings)
                if label and label != "—"
            }
        )
        for discipline in disciplines[:20]:
            items.append((discipline, "（由审查发现归纳）", "—", "自专业审查输出提取"))
    if not items:
        return ["- 未形成结构化设计要素清单，请结合正文与检查单人工整理。"]
    for index, (category, name, section, note) in enumerate(items[:80], start=1):
        rows.append(
            "| {index} | {category} | {name} | {section} | {note} |".format(
                index=index,
                category=_escape_cell(category),
                name=_escape_cell(_clip(name, 120)),
                section=_escape_cell(_clip(section, 120)),
                note=_escape_cell(note),
            )
        )
    return rows


def _user_evidence_summary_rows(
    findings: list[dict[str, Any]],
    evidences: list[dict[str, Any]],
) -> list[str]:
    rows = ["| 序号 | 来源文档 | 章节路径 | 页码 | 原文摘录 |", "| --- | --- | --- | --- | --- |"]
    collected: list[tuple[str, str, str, str, str]] = []
    seen: set[str] = set()

    def add_row(source: str, section: str, page: str, excerpt: str) -> None:
        key = f"{source}|{section}|{page}|{excerpt[:80]}"
        if key in seen:
            return
        seen.add(key)
        collected.append((source or "—", section or "—", page or "—", _clip(excerpt, 220) or "—"))

    for ev in evidences[:80]:
        add_row(
            str(ev.get("source_file_name") or ev.get("source_ref") or ""),
            str(ev.get("section_id") or ev.get("section_title") or ""),
            str(ev.get("page_no") or ev.get("page") or ""),
            str(ev.get("excerpt") or ev.get("quote") or ev.get("summary") or ""),
        )
    for finding in findings[:80]:
        source = str(finding.get("source_material_name") or finding.get("source_file_name") or "")
        section = str(finding.get("section_title") or finding.get("section_id") or finding.get("source_sheet") or "")
        page = str(finding.get("page_no") or "")
        quote = str(finding.get("source_quote") or finding.get("excerpt") or "")
        if source or section or quote:
            add_row(source, section, page, quote)
        for quote_item in _as_list(finding.get("source_quotes")):
            add_row(source, section, page, str(quote_item))

    if not collected:
        return ["- 未返回可归档的证据定位条目。"]
    for index, (source, section, page, excerpt) in enumerate(collected[:100], start=1):
        rows.append(
            "| {index} | {source} | {section} | {page} | {excerpt} |".format(
                index=index,
                source=_escape_cell(source),
                section=_escape_cell(section),
                page=_escape_cell(page),
                excerpt=_escape_cell(excerpt),
            )
        )
    return rows


def _rid_draft_rows(review_results: dict[str, Any]) -> list[str]:
    gnc = _gnc_section(review_results)
    editorial = _as_dict(gnc.get("editorial_synthesis"))
    rid_items = _as_list(editorial.get("rid_items"))
    if not rid_items:
        rid_items = _as_list(gnc.get("rid_items"))
    if not rid_items:
        return ["- 未生成审查意见单草稿条目。"]
    rows = ["| 序号 | 问题描述 | 严重度 | 整改建议 | 状态 |", "| --- | --- | --- | --- | --- |"]
    for index, item in enumerate(rid_items[:40], start=1):
        row = _as_dict(item)
        rows.append(
            "| {index} | {description} | {severity} | {recommendation} | {status} |".format(
                index=index,
                description=_escape_cell(_clip(row.get("description") or row.get("title") or row.get("summary"), 260)),
                severity=_escape_cell(
                    resolve_severity_label_zh(str(row.get("severity") or "")) or "—"
                ),
                recommendation=_escape_cell(_clip(row.get("recommendation") or row.get("corrective_action"), 220) or "—"),
                status=_escape_cell(
                    resolve_work_item_status_label_zh(str(row.get("status") or "open")) or "待处理"
                ),
            )
        )
    return rows


def _minutes_draft_lines(review_results: dict[str, Any]) -> list[str]:
    gnc = _gnc_section(review_results)
    editorial = _as_dict(gnc.get("editorial_synthesis"))
    minutes = editorial.get("minutes")
    if isinstance(minutes, dict):
        lines: list[str] = []
        for key in ("summary", "conclusion", "highlights", "residual_risks"):
            value = editorial.get(key) if key != "summary" else minutes.get("summary") or editorial.get("summary")
            if isinstance(value, list):
                lines.extend(
                    f"- {_display_conclusion_text(item) or _clip(item, 500)}"
                    for item in value[:12]
                    if str(item).strip()
                )
            elif str(value or "").strip():
                lines.append(f"- {_clip(_display_conclusion_text(value) or value, 500)}")
        action_items = _as_list(minutes.get("action_items") or minutes.get("follow_up_items"))
        for item in action_items[:12]:
            row = _as_dict(item)
            text = row.get("text") or row.get("title") or row.get("description") or item
            lines.append(f"- {_clip(text, 260)}")
        return lines or ["- 未生成结构化纪要要点。"]
    text = _display_conclusion_text(minutes) or _display_conclusion_text(editorial.get("conclusion_draft"))
    if not text:
        for _, section in _review_sections(review_results):
            text = _display_conclusion_text(section.get("review_conclusion")) or _display_conclusion_text(
                section.get("conclusion")
            )
            if text:
                break
    if not text:
        return ["- 未生成评审纪要要点。"]
    return [f"- {_clip(line, 500)}" for line in text.splitlines() if line.strip()][:20]


def _overview_task_display_name(
    *,
    objective: str,
    title: str,
    review_scope: dict[str, Any],
) -> str:
    explicit = str(objective or title or "").strip()
    generic_patterns = (
        r"^super agent run$",
        r"^super agent 审查$",
        r"^智能审查[\d./-\s]*$",
        r"^综合审查[\d./-\s]*$",
    )
    if explicit and not any(re.search(pattern, explicit, re.IGNORECASE) for pattern in generic_patterns):
        return explicit
    names = [str(item).strip() for item in _as_list(review_scope.get("material_names")) if str(item).strip()]
    if len(names) == 1:
        base = names[0].split("/")[-1]
        dot = base.rfind(".")
        return base[:dot] if dot > 0 else base
    if len(names) > 1:
        first = names[0].split("/")[-1]
        dot = first.rfind(".")
        stem = first[:dot] if dot > 0 else first
        return f"{stem} 等 {len(names)} 份材料"
    return explicit or title or "审查任务"


def _merge_workbench_overview_snapshot(
    *,
    conclusion_payload: dict[str, Any],
    metadata: dict[str, Any],
    bundle: dict[str, Any],
    problem_count: int = 0,
) -> dict[str, Any]:
    snapshot = _as_dict(metadata.get("workbench_overview"))
    review_scope = _as_dict(conclusion_payload.get("review_scope"))
    buckets = _as_dict(conclusion_payload.get("issue_buckets"))
    issue_summary = _as_dict(conclusion_payload.get("issue_summary"))
    material_count = int(snapshot.get("material_count") or len(_as_list(bundle.get("materials")) or []))
    bucket_problem_count = count_problem_buckets(buckets)
    pending_confirm = int(snapshot.get("pending_confirm") or issue_summary.get("pending_confirm") or 0)
    if not pending_confirm:
        pending_confirm = int(buckets.get("manual_review") or 0)
    issue_count = int(snapshot.get("issue_count") or problem_count or bucket_problem_count or 0)

    verdict_label = str(
        snapshot.get("verdict_label_zh")
        or conclusion_payload.get("verdict_label_zh")
        or resolve_verdict_label_zh(str(conclusion_payload.get("verdict") or metadata.get("verdict") or ""))
    ).strip()
    rationale_zh = str(
        snapshot.get("rationale_zh") or conclusion_payload.get("rationale_zh") or ""
    ).strip()
    one_line = str(
        snapshot.get("one_line_conclusion")
        or conclusion_payload.get("one_line_conclusion")
        or conclusion_payload.get("headline_verdict")
        or ""
    ).strip()

    subject_lines = _as_list(snapshot.get("review_subject_lines"))
    if not subject_lines:
        subject_lines = _as_list(review_scope.get("material_summary_lines")) or _as_list(
            review_scope.get("material_names")
        )
    plan_lines = _as_list(snapshot.get("review_plan_lines"))
    if not plan_lines:
        plan_lines = _as_list(review_scope.get("review_plan_lines")) or _as_list(review_scope.get("actual_scope"))

    return {
        "task_name": str(snapshot.get("task_name") or "").strip(),
        "run_status": str(snapshot.get("run_status") or "已完成").strip() or "已完成",
        "workbench_phase": str(snapshot.get("workbench_phase") or "已完成").strip() or "已完成",
        "current_step": str(snapshot.get("current_step") or "").strip(),
        "material_count": material_count,
        "review_route_label": str(
            snapshot.get("review_route_label") or review_scope.get("review_mode_label") or ""
        ).strip(),
        "issue_count": issue_count,
        "pending_confirm": pending_confirm,
        "quality_status": str(snapshot.get("quality_status") or "正常").strip() or "正常",
        "verdict_label_zh": verdict_label or "待形成结论",
        "rationale_zh": rationale_zh,
        "one_line_conclusion": one_line or verdict_label,
        "review_subject_lines": [str(line).strip() for line in subject_lines if str(line).strip()],
        "review_plan_lines": [str(line).strip() for line in plan_lines if str(line).strip()],
    }


def _render_workbench_overview_lines(
    *,
    overview: dict[str, Any],
    objective: str,
    title: str,
) -> list[str]:
    task_name = str(overview.get("task_name") or "").strip() or _overview_task_display_name(
        objective=objective,
        title=title,
        review_scope={
            "material_names": overview.get("review_subject_lines") or [],
        },
    )
    current_step = str(overview.get("current_step") or "").strip()
    phase_line = str(overview.get("workbench_phase") or "—")
    if current_step and not _is_likely_step_id(current_step):
        phase_line = f"{phase_line}（{current_step}）"
    elif current_step:
        phase_line = f"{phase_line}（{_humanize_step_key(current_step)}）"

    situation_rows = [
        ("运行状态", overview.get("run_status") or "—"),
        ("当前阶段", phase_line),
        ("材料数量", overview.get("material_count") if overview.get("material_count") not in (None, "") else "—"),
        ("审查路线", overview.get("review_route_label") or "待识别"),
        ("问题数量", overview.get("issue_count") if overview.get("issue_count") not in (None, "") else "—"),
        ("待确认事项", overview.get("pending_confirm") if overview.get("pending_confirm") not in (None, "") else "—"),
        ("质量状态", overview.get("quality_status") or "—"),
    ]

    lines: list[str] = [
        "## 2. 审查总览",
        "",
        "### 2.1 审查概况",
        "",
        "| 项目 | 内容 |",
        "| --- | --- |",
    ]
    for label, value in situation_rows:
        lines.append(f"| {label} | {_escape_cell(value)} |")
    lines.extend(
        [
            "",
            "### 2.2 审查任务详情",
            "",
            f"- 审查任务：{_clip(task_name, 200)}",
        ]
    )
    subject_lines = _as_list(overview.get("review_subject_lines"))
    if subject_lines:
        lines.append("- 审查对象：")
        lines.extend(f"  - {_clip(line, 260)}" for line in subject_lines)
    plan_lines = _as_list(overview.get("review_plan_lines"))
    if plan_lines:
        lines.append("- 审查方案：")
        lines.extend(f"  - {_clip(line, 260)}" for line in plan_lines)
    lines.extend(
        [
            "",
            "### 2.3 裁定结论",
            "",
            f"- 裁定结论：{overview.get('verdict_label_zh') or '待形成结论'}",
        ]
    )
    if overview.get("rationale_zh"):
        lines.append(f"- 结论说明：{_clip(overview.get('rationale_zh'), 1200)}")
    lines.append(f"- 一句话结论：{_clip(overview.get('one_line_conclusion') or overview.get('verdict_label_zh'), 400)}")
    lines.append("")
    return lines


def _is_likely_step_id(value: str) -> bool:
    token = str(value or "").strip()
    if not token:
        return False
    if _contains_cjk(token):
        return False
    return "_" in token or token.isascii()


def _contains_cjk(text: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in str(text or ""))


def _humanize_step_key(step_key: str) -> str:
    mapping = {
        "classify_and_route": "分类与路由",
        "document_parse": "文档解析",
        "structure_materials": "材料结构化",
        "bootstrap_review_plus_task": "启动文件组审查",
        "run_review_plus": "文件组审查",
        "run_gnc_review": "GNC 审查",
        "smart_review_committee": "智能专家委员会",
        "review_results": "审查结论汇总",
        "review_intake": "送审材料接收",
        "quality_screening": "质量筛查",
        "document_structuring": "文档结构化",
        "discipline_review": "专业审查",
        "cross_document_review": "跨文档一致性",
        "editorial_synthesis": "意见汇总",
        "chief_decision": "总师裁定",
    }
    key = str(step_key or "").strip().lower()
    return mapping.get(key, step_key.replace("_", " "))


def _chief_review_lines(review_results: dict[str, Any], grouped: dict[str, list[dict[str, Any]]]) -> list[str]:
    gnc = _gnc_section(review_results)
    chief = _as_dict(gnc.get("chief_decision"))
    arbitration = _as_dict(gnc.get("arbitration"))
    lines: list[str] = []
    verdict = str(chief.get("verdict") or "").strip()
    rationale = str(chief.get("rationale") or "").strip()
    if verdict:
        lines.append(f"- 总师预检结论：{resolve_verdict_label_zh(verdict)}")
    if rationale:
        lines.append(f"- 审定说明：{_clip(rationale, 500)}")
    for risk in _as_list(chief.get("key_risks"))[:8]:
        lines.append(f"- 关键风险：{_clip(risk, 260)}")
    for item in _as_list(arbitration.get("arbitration_items") or chief.get("arbitration_items"))[:8]:
        lines.append(f"- 待仲裁/审定：{_clip(item, 260)}")
    if grouped.get("critical"):
        lines.append(f"- 重大问题 {len(grouped['critical'])} 项，须总师组织专项审定。")
    if grouped.get("pending_expert"):
        lines.append(f"- 待专家确认 {len(grouped['pending_expert'])} 项，正式放行前须人工复核。")
    if not lines:
        lines.append("- 暂无需总师单独审定的事项；请结合专业审查发现人工确认。")
    return lines


def build_user_review_report(input_data: ReviewReportInput | dict[str, Any]) -> ReviewReportArtifact:
    """Generate a user-facing GNC review report aligned with official output categories."""
    data = input_data if isinstance(input_data, ReviewReportInput) else ReviewReportInput.model_validate(input_data)
    bundle = _structured_bundle(data)
    review_results = data.review_results
    quality = data.quality_report
    findings = _extract_findings(review_results)
    evidences = _extract_evidences(bundle, review_results)
    review_mode = _resolve_review_mode(data.review_type)
    context = _review_context(data, review_results)
    grouped = _group_findings_by_official_category(findings, review_mode=review_mode)

    cross_doc_items: list[dict[str, Any]] = []
    for _, section in _review_sections(review_results):
        cross_doc_items.extend(_as_list(section.get("cross_doc_findings")))
        cross_doc_items.extend(_as_list(section.get("cross_document_items")))
        report = _as_dict(section.get("report"))
        cross_doc_items.extend(_as_list(report.get("cross_document_items")))

    primary_verdict = _extract_report_verdict(review_results, data.metadata)
    conclusion_payload = build_conclusion_payload(
        review_mode=review_mode,  # type: ignore[arg-type]
        verdict=primary_verdict,
        rationale=str(data.metadata.get("rationale") or ""),
        findings=findings,
        cross_doc_items=cross_doc_items,
        materials=_as_list(bundle.get("materials")),
        explicit_scope=context["review_scope"],
        scenario=context["review_phase"],
        total_check_items=len(findings),
        evidence_count=len(evidences),
    )

    legacy_markdown = ""
    for _, section in _review_sections(review_results):
        legacy_markdown = str(section.get("legacy_markdown") or legacy_markdown)

    title = str(data.metadata.get("title") or _DEFAULT_REPORT_TITLE)
    objective = str(data.metadata.get("objective") or "")
    generated_at = datetime.now().strftime("%Y-%m-%d")
    check_stats = _resolve_check_item_stats(findings, review_results, bundle)
    total = check_stats["total"]
    satisfied = check_stats["satisfied"]
    not_satisfied = check_stats["not_satisfied"]
    insufficient = check_stats["insufficient"]
    overview_snapshot = _merge_workbench_overview_snapshot(
        conclusion_payload=conclusion_payload,
        metadata=data.metadata,
        bundle=bundle,
        problem_count=count_problem_buckets(_as_dict(conclusion_payload.get("issue_buckets"))),
    )
    if not overview_snapshot.get("task_name"):
        overview_snapshot["task_name"] = objective or title

    lines: list[str] = [
        f"# {title}",
        "",
        "## 1. 基本信息",
        "",
        f"- 产品型号：{context['product_model']}",
        f"- 审查阶段：{context['review_phase']}",
        f"- 审查范围：{context['review_scope']}",
        f"- 审查任务：{objective or title}",
        f"- 审查日期：{generated_at}",
        "",
        "**来源材料**",
        "",
        *_user_material_rows(bundle),
        "",
        *_render_workbench_overview_lines(
            overview=overview_snapshot,
            objective=objective,
            title=title,
        ),
        "## 3. 材料质量结论",
        "",
        *_material_quality_lines(bundle, quality, review_results),
        "",
        "## 4. 总体审查结论",
        "",
        f"- 裁定结论：{overview_snapshot.get('verdict_label_zh') or '—'}",
        f"- 一句话结论：{overview_snapshot.get('one_line_conclusion') or '—'}",
        f"- 结论说明：{overview_snapshot.get('rationale_zh') or '—'}",
        f"- 检查项统计：共 {total} 项；符合 {satisfied} 项；不符合 {not_satisfied} 项；证据不足 {insufficient} 项。",
        "",
    ]
    for index, (name, section) in enumerate(_review_sections(review_results), start=1):
        label = _USER_SECTION_LABELS.get(name, name)
        lines.extend(
            [
                f"### 4.{index} {label}",
                f"- 结论：{_review_conclusion(section) or '尚未形成审查结论。'}",
                "",
            ]
        )
    if not _review_sections(review_results):
        lines.extend(["- 尚未形成分专业审查结论。", ""])

    lines.extend(["## 5. 专业审查发现", ""])
    for section_index, (category_key, category_label) in enumerate(_OFFICIAL_FINDING_CATEGORIES, start=1):
        category_findings = grouped.get(category_key) or []
        lines.extend([f"### 5.{section_index} {category_label}", ""])
        lines.extend(_render_official_finding_entries(category_findings))
        lines.append("")

    lines.extend(
        [
            "## 6. 证据定位汇总",
            "",
            *_user_evidence_summary_rows(findings, evidences),
            "",
            "## 7. 结论草稿",
            "",
            "### 7.1 审查意见单草稿",
            "",
            *_rid_draft_rows(review_results),
            "",
            "### 7.2 评审纪要要点",
            "",
            *_minutes_draft_lines(review_results),
            "",
            "### 7.3 需总师审定事项",
            "",
            *_chief_review_lines(review_results, grouped),
            "",
            "## 8. 审签栏",
            "",
            *_user_signature_block(),
            "",
            "## 附件 A：设计要素清单",
            "",
            *_design_element_rows(bundle, findings),
            "",
            "## 附件 B：符合性检查清单",
            "",
            f"- 统计：共 {total} 项；符合 {satisfied} 项；不符合 {not_satisfied} 项；证据不足 {insufficient} 项。",
            "",
            *_user_checklist_rows(findings),
            "",
        ]
    )
    if legacy_markdown.strip() and not is_internal_review_report(legacy_markdown):
        lines.extend(["## 附：专项审查摘要", "", legacy_markdown.strip(), ""])

    return ReviewReportArtifact(
        report_id=data.report_id,
        title=title,
        markdown=localize_report_markdown("\n".join(lines).strip() + "\n"),
        review_index={},
        render_blocks=[],
        source_parse_artifact_id="",
        source_review_ids=[],
    )


def _render_evidence_index(evidences: list[dict[str, Any]], index: dict[str, Any]) -> list[str]:
    if not evidences:
        return ["- 未返回证据索引。"]
    lines = ["| Evidence ID | 文件 | Section | 摘录 |", "| --- | --- | --- | --- |"]
    for ev in evidences[:120]:
        ev_id = str(ev.get("evidence_id") or ev.get("id"))
        anchor_id = _anchor(ev_id, "evidence")
        index["evidences"].append(
            {
                "evidence_id": ev_id,
                "anchor_id": anchor_id,
                "source_file_name": ev.get("source_file_name") or ev.get("source_ref", ""),
                "section_id": ev.get("section_id", ""),
            }
        )
        lines.append(
            "| {id} | {file} | {section} | {excerpt} |".format(
                id=f'<a id="{anchor_id}"></a>`{_escape_cell(ev_id)}`',
                file=_escape_cell(ev.get("source_file_name") or ev.get("source_ref")),
                section=_escape_cell(ev.get("section_id")),
                excerpt=_escape_cell(_clip(ev.get("excerpt") or ev.get("quote") or ev.get("summary"), 180)),
            )
        )
    return lines


def build_review_report(input_data: ReviewReportInput | dict[str, Any]) -> ReviewReportArtifact:
    data = input_data if isinstance(input_data, ReviewReportInput) else ReviewReportInput.model_validate(input_data)
    if data.audience == "user":
        return build_user_review_report(data)
    bundle = _structured_bundle(data)
    ir = _document_ir(bundle)
    review_results = data.review_results
    quality = data.quality_report
    findings = _extract_findings(review_results)
    evidences = _extract_evidences(bundle, review_results)
    human_items: list[str] = []
    review_index: dict[str, Any] = {
        "findings": [],
        "evidences": [],
        "structured_elements": [],
    }
    title = str(data.metadata.get("title") or "Super Agent 统一审查报告")
    source_review_ids = [
        str(value)
        for value in (
            data.metadata.get("review_plus_id"),
            data.metadata.get("gnc_review_id"),
            data.metadata.get("review_id"),
        )
        if value
    ]

    lines: list[str] = [
        f"# {title}",
        "",
        "## 1. 任务与材料概述",
        "",
        f"- Report ID: `{data.report_id}`",
        f"- Review type: `{data.review_type}`",
        f"- Generated at: {datetime.now().isoformat()}",
        f"- Objective: {data.metadata.get('objective', '')}",
        "",
        *_material_rows(bundle),
        "",
        "## 2. 解析与结构化质量",
        "",
        *_quality_lines(bundle, quality),
        "",
        "## 3. 结构化解析结果",
        "",
        "### 3.1 Layout 摘要",
        "",
        *_render_layout_summary(ir),
        "",
        "### 3.2 表格",
        "",
        *_render_table_elements(ir, review_index),
        "",
        "### 3.3 公式",
        "",
        *_render_formula_elements(bundle, review_index),
        "",
        "### 3.4 图片与视觉元素",
        "",
        *_render_visual_elements(ir, review_index, human_items),
        "",
        "### 3.5 流程图/框图",
        "",
        *_render_graph_elements(ir, review_index, human_items),
        "",
        "### 3.6 图表",
        "",
        *_render_chart_elements(ir, review_index, human_items),
        "",
        "## 4. 审查结论",
        "",
    ]
    for name, section in _review_sections(review_results):
        lines.extend(
            [
                f"### {name}",
                f"- Status: {section.get('status', '')}",
                f"- Conclusion: {_review_conclusion(section)}",
                f"- Report source: {section.get('review_plus_id') or section.get('review_id') or section.get('gnc_review_id') or ''}",
                "",
            ]
        )
    if not _review_sections(review_results):
        lines.extend(["- 未返回审查结果；当前报告仅包含解析产物。", ""])
    lines.extend(
        [
            "## 5. Findings 与问题闭环",
            "",
            *_render_findings(findings, review_index, human_items),
            "",
            "## 6. 证据与标准来源索引",
            "",
            *_render_evidence_index(evidences, review_index),
            "",
            "## 7. 人工复核项",
            "",
        ]
    )
    if human_items:
        lines.extend(f"- {item}" for item in human_items[:100])
    else:
        lines.append("- 未识别到必须人工复核的结构化元素或 finding。")
    lines.extend(
        [
            "",
            "## 附录 A：解析产物摘要",
            "",
            "```json",
            json.dumps(_as_dict(bundle.get("stats")), ensure_ascii=False, indent=2),
            "```",
            "",
            "## 附录 B：原始结构化数据索引",
            "",
            "```json",
            json.dumps(review_index, ensure_ascii=False, indent=2),
            "```",
            "",
        ]
    )
    return ReviewReportArtifact(
        report_id=data.report_id,
        title=title,
        markdown="\n".join(lines).strip() + "\n",
        review_index=review_index,
        render_blocks=[],
        source_parse_artifact_id=str(data.parse_artifact.get("artifact_id") or ""),
        source_review_ids=source_review_ids,
    )
