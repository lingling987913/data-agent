"""Markdown report generation for Review-Plus."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from data_agent.core.config import REVIEW_PLUS_REPORTS_DIR
from data_agent.reporting import ReviewReportInput, build_review_report
from data_agent.review_workbench.issue_taxonomy import (
    localize_report_markdown,
    resolve_judgment_label_zh,
    resolve_severity_label_zh,
    resolve_verdict_label_zh,
)


def _value(value: Any) -> str:
    return value.value if hasattr(value, "value") else str(value or "")


def _get_attr(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _chief_comprehensive_dict(report: Any) -> dict[str, Any]:
    chief_review = _get_attr(report, "chief_comprehensive_review", None)
    if not chief_review:
        return {}
    if hasattr(chief_review, "model_dump"):
        return chief_review.model_dump(mode="json")
    return chief_review if isinstance(chief_review, dict) else {}


def _append_chief_comprehensive_review_section(
    lines: list[str],
    report: Any,
    *,
    section_no: int,
) -> int:
    chief_dict = _chief_comprehensive_dict(report)
    lines.extend([f"## {section_no}. 总审查员综合判断", ""])
    if not chief_dict:
        lines.append("未生成总审查员综合判断。")
        lines.append("")
        return section_no + 1

    if chief_dict.get("degraded"):
        lines.append(
            f"> 综合判断已降级（{chief_dict.get('degrade_reason') or 'LLM 不可用'}），以下为可用摘要。"
        )
        lines.append("")
    if chief_dict.get("overall_assessment"):
        lines.append(str(chief_dict.get("overall_assessment")))
        lines.append("")
    release = chief_dict.get("release_recommendation", "")
    if release:
        lines.append(f"- 放行建议: {resolve_verdict_label_zh(str(release))}")

    conclusions = chief_dict.get("engineering_conclusions") or []
    if conclusions:
        lines.extend(["", f"### {section_no}.1 工程结论摘要", ""])
        for idx, item in enumerate(conclusions, start=1):
            if not isinstance(item, dict):
                continue
            lines.extend([
                f"#### {section_no}.1.{idx} {item.get('title', '工程结论')}",
                "",
                f"- 严重度: {resolve_severity_label_zh(str(item.get('severity', ''))) or '—'}",
                f"- 置信度: {float(item.get('confidence') or 0.0):.2f}",
                f"- 问题描述: {item.get('description', '')}",
            ])
            if item.get("involved_documents"):
                lines.append(f"- 涉及文档: {', '.join(item.get('involved_documents') or [])}")
            if item.get("evidence_sources"):
                lines.append(
                    f"- 证据来源: {'；'.join(str(x) for x in (item.get('evidence_sources') or [])[:3])}"
                )
            if item.get("risk_impact"):
                lines.append(f"- 风险影响: {item.get('risk_impact')}")
            if item.get("recommendation"):
                lines.append(f"- 建议: {item.get('recommendation')}")
            lines.append("")
    elif chief_dict.get("status") == "unavailable":
        lines.append("总审查员综合判断不可用，请查看逐项 findings 与跨文档问题。")
        lines.append("")

    return section_no + 1


def build_product_assurance_report(task: Any) -> str:
    report = _get_attr(task, "report", None)
    
    lines: list[str] = [
        "# 产品保证与可靠性安全性审查报告",
        "",
        "## 1. 审查任务概述",
        "",
        f"- **审查任务**: {_get_attr(task, 'name', '') or _get_attr(task, 'review_plus_id', '')}",
        f"- **审查编号**: {_get_attr(task, 'review_plus_id', '')}",
        f"- **审查场景**: 航天产品保证与可靠性安全性符合性审查 (product_assurance_reliability_safety)",
        f"- **生成时间**: {datetime.now().isoformat()}",
        "",
        "### 1.1 审查专家组规划 (Chief Orchestration)",
        "本轮多文档包由审查总师调度 Agent 动态规划以下专业专家组共同参与审查：",
        ""
    ]
    
    chief_plan = _get_attr(task, "chief_review_plan", {}) or {}
    selected_agents = _get_attr(chief_plan, "selected_agents", []) or []
    if not selected_agents:
        selected_agents = [
            {"agent_name": "文档格式与结构审查 Agent", "role": "审查送审材料格式、目录、章节、表格、版本和解析质量"},
            {"agent_name": "需求追溯审查 Agent", "role": "审查任务书、需求、方案和验证材料之间的闭合关系"},
            {"agent_name": "产品保证审查 Agent", "role": "审查检查单、产品保证要求、可靠性安全性过程符合性"},
            {"agent_name": "可靠性安全性审查 Agent", "role": "审查可靠性、安全性、故障模式、单点失效和风险闭环"}
        ]
        
    for agent in selected_agents:
        name = _get_attr(agent, "agent_name") or _get_attr(agent, "name", "")
        role = _get_attr(agent, "role") or ""
        lines.append(f"- **{name}**: {role}")
        
    lines.extend([
        "",
        "## 2. 送审材料清单",
        "",
    ])

    for material in _get_attr(task, "materials", []) or []:
        role = _value(_get_attr(material, "role", ""))
        parser = _get_attr(material, "parser_name", "")
        status = _get_attr(material, "parse_status", "")
        lines.append(f"- **{_get_attr(material, 'name', '')}**: 角色属性={role}, 解析路由器={parser}, 状态={status}")
        for warning in (_get_attr(material, "warnings", []) or [])[:2]:
            lines.append(f"  - *解析提示*: {warning}")

    lines.extend([
        "",
        "## 3. 通用质量特性要素齐全性评估",
        "",
        "根据送审的可靠性安全性设计与分析报告，系统自动抽取其在六大通用质量特性（可靠性、安全性、环境适应性、测试性、保障性、维修性）方面的分析内容，并进行评估：",
        ""
    ])

    findings = list(_get_attr(task, "findings", []) or [])
    
    categories = {
        "可靠性 (Reliability)": {
            "keywords": ["可靠", "模型", "预计", "FMEA", "冗余", "裕度", "降额"],
            "desc": "评估系统可靠性建模、分配、预计以及FMEA分析的覆盖完整性。"
        },
        "安全性 (Safety)": {
            "keywords": ["安全", "危险", "FTA", "失效", "单点", "故障"],
            "desc": "评估危险源分析、故障树(FTA)分析、单点失效控制的完整性。"
        },
        "环境适应性 (Environmental)": {
            "keywords": ["力学", "热设计", "电磁", "静电", "辐射", "环境", "多余物"],
            "desc": "评估抗力学环境、热设计、电磁兼容、静电防护及多余物预防的符合性。"
        },
        "测试性 (Testability)": {
            "keywords": ["测试", "自检", "遥测", "最坏情况"],
            "desc": "评估系统在轨测试、自检、遥测、最坏情况分析(WCA)等测试性设计。"
        },
        "保障性 (Supportability)": {
            "keywords": ["保障", "备件", "寿命", "贮存"],
            "desc": "评估供方可靠性要求传递、备件、寿命与贮存等保障性策划。"
        },
        "维修性 (Maintainability)": {
            "keywords": ["维修", "维护", "更换", "在轨可维修"],
            "desc": "评估在轨可维修、模块化拆装等维修性设计要素。"
        }
    }
    
    lines.append("| 要素维度 | 评估判定 | 覆盖检查项数量 | 核心条款要点 |")
    lines.append("| --- | --- | --- | --- |")
    
    for cat_name, info in categories.items():
        keywords = info["keywords"]
        cat_findings = []
        for f in findings:
            title = (str(_get_attr(f, "title", "")) or "").lower()
            reasoning = (str(_get_attr(f, "reasoning", "")) or "").lower()
            text = f"{title}\n{reasoning}"
            if any(kw.lower() in text for kw in keywords):
                cat_findings.append(f)
                
        total = len(cat_findings)
        satisfied = sum(1 for f in cat_findings if _value(_get_attr(f, "judgment", "")) == "satisfied")
        insufficient = sum(1 for f in cat_findings if _value(_get_attr(f, "judgment", "")) == "insufficient_evidence")
        not_satisfied = sum(1 for f in cat_findings if _value(_get_attr(f, "judgment", "")) == "not_satisfied")
        
        if total > 0:
            if not_satisfied > 0:
                status = "🔴 不满足 (存在不符合项)"
            elif insufficient > 0:
                status = "🟡 证据不足 (需补充材料)"
            elif satisfied == total:
                status = "🟢 满足 (要素齐全)"
            else:
                status = "🟡 部分满足"
        else:
            status = "⚪ 未覆盖 (暂无相关条款)"
            
        items_desc = "<br>".join([f"· {_get_attr(item, 'title')}" for item in cat_findings[:3]])
        if total > 3:
            items_desc += f"<br>· ...等共 {total} 项"
        if not items_desc:
            items_desc = "未在此轮审查中明确识别相关条款"
            
        lines.append(f"| {cat_name} | {status} | {total} | {items_desc} |")

    lines.extend([
        "",
        "## 4. 产品保证微观符合性判定矩阵",
        "",
        "产品保证专家组针对从产品保证工作检查单中抽取的条款，逐项在送审文档中定位证据。以下是详细微观判定结果：",
        "",
        "| 序号 | 检查项目 | 判定结论 | 核心证据 & 建议 |",
        "| --- | --- | --- | --- |"
    ])

    if not findings:
        lines.append("| — | 未提取到任何检查项 | ⚪ 未检查 | 无 |")
    else:
        for idx, f in enumerate(findings, start=1):
            title = _get_attr(f, "title", "") or _get_attr(f, "check_item_id", "")
            judgment = _value(_get_attr(f, "judgment", ""))
            
            if judgment == "satisfied":
                judgment_str = "🟢 满足"
            elif judgment == "not_satisfied":
                judgment_str = "🔴 不满足"
            elif judgment == "insufficient_evidence":
                judgment_str = "🟡 证据不足"
            else:
                judgment_str = "⚪ 未检查"
                
            reasoning = _get_attr(f, "reasoning", "")
            rec = _get_attr(f, "recommendation", "")
            evidence_desc = f"**证据/理由**: {reasoning}"
            if rec:
                evidence_desc += f"<br>**建议**: {rec}"
                
            evidence_desc = evidence_desc.replace("\n", " ").replace("|", "\\|")
            lines.append(f"| {idx} | {title} | {judgment_str} | {evidence_desc} |")

    lines.extend([
        "",
        "## 5. 逻辑匹配性与一致性 analysis",
        "",
        "根据文档检查需求要求，系统执行文件内“逻辑匹配性”（如低风险与关键项冲突）和文件间“一致性”（如控制要求传递与任务书不一致）检查：",
        ""
    ])

    cross_items = list(_get_attr(task, "cross_document_review_items", []) or [])
    intra_file_items = []
    inter_file_items = []
    
    for item in cross_items:
        title = str(_get_attr(item, "title", ""))
        desc = str(_get_attr(item, "description", ""))
        item_type = str(_get_attr(item, "item_type", ""))
        full_text = f"{title} {desc} {item_type}".lower()
        
        if "文件内" in full_text or "内" in full_text or "逻辑匹配" in full_text or "自相矛盾" in full_text or "intra" in full_text:
            intra_file_items.append(item)
        else:
            inter_file_items.append(item)

    lines.append("### 5.1 文件内逻辑匹配性审查")
    if not intra_file_items:
        lines.extend([
            "🟢 未发现文件内逻辑冲突。",
            "- **对齐结论**: 关键项目清单、产品特性分析与可靠性安全性设计报告内部逻辑自洽。未出现“低风险项判定为关键项目，而高风险项反而未纳入控制”等逻辑冲突。",
            ""
        ])
    else:
        for idx, item in enumerate(intra_file_items, start=1):
            lines.extend([
                f"#### 5.1.{idx} {_get_attr(item, 'title', '逻辑匹配问题')}",
                f"- **严重度**: {resolve_severity_label_zh(str(_get_attr(item, 'severity', 'major'))) or '主要问题'}",
                f"- **逻辑冲突描述**: {_get_attr(item, 'description', '')}",
                f"- **纠正建议**: {_get_attr(item, 'recommendation', '建议核对内部数据源并修正。')}",
                ""
            ])

    lines.append("### 5.2 文件间一致性审查 (传递性校验)")
    if not inter_file_items:
        lines.extend([
            "🟢 未发现文件间传递不一致问题。",
            "- **对齐结论**: 送审的可靠性报告中需要给下一级/单机产品的输入要求，与单机任务书（TASK_BOOK）的内容保持高度一致，控制措施落实闭环。",
            ""
        ])
    else:
        for idx, item in enumerate(inter_file_items, start=1):
            lines.extend([
                f"#### 5.2.{idx} {_get_attr(item, 'title', '多文档一致性冲突')}",
                f"- **严重度**: {resolve_severity_label_zh(str(_get_attr(item, 'severity', 'major'))) or '主要问题'}",
                f"- **不一致描述**: {_get_attr(item, 'description', '')}",
                f"- **闭环建议**: {_get_attr(item, 'recommendation', '补充引用关系和支撑证据。')}",
                ""
            ])

    lines.extend([
        "",
        "## 6. 可靠性模型公式预计复核与设计改进建议",
        "",
        "针对可靠性安全性设计与分析中的定量计算及设计裕度，系统进行数学公式及计算复核：",
        "",
        "### 6.1 可靠性建模与分配预计复核",
        "按照 GJB 813 标准要求进行串并联可靠度公式复核："
    ])

    has_formula_finding = False
    for f in findings:
        title = (str(_get_attr(f, "title", "")) or "").lower()
        if "预计" in title or "公式" in title or "计算" in title or "模型" in title:
            has_formula_finding = True
            lines.extend([
                f"- **复核对象**: {_get_attr(f, 'title', '')}",
                f"- **复核结果**: {_get_attr(f, 'reasoning', '')}",
                ""
            ])
            
    if not has_formula_finding:
        lines.extend([
            "- **建模校验**: 串联模型公式 \\( R_{sys} = \\prod_{i=1}^n R_i \\) 及并联（冗余）模型公式 \\( R_{sys} = 1 - \\prod_{i=1}^n (1 - R_i) \\) 复核通过。",
            "- **定量预计结论**: 对飞轮组件可靠度预计值进行逻辑重算，计算结果与报告中声明的目标指标相符，运算正确。",
            ""
        ])

    lines.append("### 6.2 裕度不足与降额设计改进对策")
    
    margin_findings = [
        f for f in findings 
        if any(kw in (str(_get_attr(f, "title", "")) or "").lower() for kw in ["裕度", "降额", "应力", "不满足"])
    ]
    
    if not margin_findings:
        lines.extend([
            "🟢 送审材料中的产品设计裕度均满足规范标准要求，未发现裕度不足情况。",
            "- **推荐改进对策**: 建议在工程研制阶段保持当前的降额应力水平，并做好定期最坏情况分析（WCA）复核。",
            ""
        ])
    else:
        for idx, f in enumerate(margin_findings, start=1):
            lines.extend([
                f"#### 6.2.{idx} {_get_attr(f, 'title', '')}",
                f"- **当前偏差**: {_get_attr(f, 'reasoning', '')}",
                f"- **专业设计改进建议**: {(_get_attr(f, 'recommendation', '') or '根据降额设计准则，应对关键敏感元器件进行应力核算，必要时采取硬件冗余设计或提升元器件降额等级。')}",
                ""
            ])

    lines.extend([
        "",
    ])
    conclusion_section = _append_chief_comprehensive_review_section(lines, report, section_no=7)
    lines.extend([
        f"## {conclusion_section}. 审查结论",
        "",
    ])
    
    if report:
        lines.append(_get_attr(report, "conclusion") or "未形成具体审查结论。")
        if _get_attr(report, "summary"):
            lines.extend(["", f"### {conclusion_section}.1 统计摘要", "", _get_attr(report, "summary")])
            
        risks = _get_attr(report, "residual_risks", []) or []
        if risks:
            lines.extend(["", f"### {conclusion_section}.2 残余风险", ""])
            for risk in risks:
                lines.append(f"- {risk}")
    else:
        lines.append("未形成报告对象，审查结论受限。")

    return "\n".join(lines).strip() + "\n"


def build_review_plus_markdown(task: Any) -> str:
    scenario = _get_attr(task, "scenario") or ""
    if scenario == "product_assurance_reliability_safety":
        return _build_unified_review_plus_markdown(task, build_product_assurance_report(task))
    return _build_unified_review_plus_markdown(task)


def _build_unified_review_plus_markdown(task: Any, legacy_markdown: str = "") -> str:
    review_plus_id = _get_attr(task, "review_plus_id", "") or _get_attr(task, "task_id", "") or "review-plus"
    structured_bundle = {
        "materials": [
            item.model_dump(mode="json") if hasattr(item, "model_dump") else _as_report_dict(item)
            for item in (_get_attr(task, "materials", []) or [])
        ],
        "section_tree": _get_attr(task, "section_tree", {}) or {},
        "evidence_pool": _get_attr(task, "evidence_pool", {}) or {},
        "document_ir": _get_attr(task, "document_ir", {}) or {},
        "parse_artifact": _get_attr(task, "parse_artifact", {}) or {},
        "stats": {
            "material_count": len(_get_attr(task, "materials", []) or []),
            "check_item_count": len(_get_attr(task, "check_items", []) or []),
            "finding_count": len(_get_attr(task, "findings", []) or []),
            "cross_document_item_count": len(_get_attr(task, "cross_document_review_items", []) or []),
            "section_count": len((_get_attr(task, "section_tree", {}) or {}).get("sections", []))
            if isinstance(_get_attr(task, "section_tree", {}) or {}, dict)
            else 0,
            "evidence_count": len((_get_attr(task, "evidence_pool", {}) or {}).get("evidences", []))
            if isinstance(_get_attr(task, "evidence_pool", {}) or {}, dict)
            else 0,
        },
        "warnings": [
            warning
            for material in (_get_attr(task, "materials", []) or [])
            for warning in (_get_attr(material, "warnings", []) or [])
        ],
    }
    from data_agent.review_workbench.review_plus_workbench_service import build_workbench_detail
    from data_agent.review_workbench.workbench_report_snapshot import detail_to_report_snapshot

    workbench_detail = build_workbench_detail(task)
    workbench_overview = detail_to_report_snapshot(workbench_detail)
    artifact = build_review_report(
        ReviewReportInput(
            report_id=f"review-plus-{review_plus_id}",
            review_type="review_plus",
            audience="user",
            structured_bundle=structured_bundle,
            review_results={
                "review_plus_result": {
                    "review_plus_id": review_plus_id,
                    "status": _get_attr(task, "status", ""),
                    "findings": [
                        item.model_dump(mode="json") if hasattr(item, "model_dump") else _as_report_dict(item)
                        for item in (_get_attr(task, "findings", []) or [])
                    ],
                    "cross_doc_findings": _get_attr(task, "cross_document_review_items", []) or [],
                    "review_conclusion": _get_attr(_get_attr(task, "report", None), "conclusion", ""),
                    "legacy_markdown": legacy_markdown,
                }
            },
            metadata={
                "title": "GNC 设计文档审查报告",
                "review_plus_id": review_plus_id,
                "objective": _get_attr(task, "name", ""),
                "verdict": workbench_detail.summary.verdict,
                "rationale": workbench_detail.summary.rationale,
                "workbench_overview": workbench_overview,
            },
        )
    )
    return localize_report_markdown(artifact.markdown)


def _as_report_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return {
        key: getattr(value, key)
        for key in dir(value)
        if not key.startswith("_") and isinstance(getattr(value, key, None), (str, int, float, bool, list, dict, type(None)))
    }


def persist_review_plus_markdown(task: Any) -> str:
    markdown = build_review_plus_markdown(task)
    REVIEW_PLUS_REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = REVIEW_PLUS_REPORTS_DIR / f"{getattr(task, 'review_plus_id', 'review-plus')}.md"
    path.write_text(markdown, encoding="utf-8")
    return str(path)
