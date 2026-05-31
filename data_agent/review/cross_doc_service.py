from __future__ import annotations

import re
from typing import Iterable

from data_agent.review.schemas import CrossDocFinding, ParsedMaterial, ReviewPlusMaterialRole

_KEY_TOPICS = [
    "FMEA", "FTA", "关键项目", "可靠性", "安全性", "裕度", "环境适应性",
    "任务剖面", "飞轮", "控制律", "带宽", "角动量", "轴承", "寿命试验",
]


def _content(material: ParsedMaterial) -> str:
    return material.content or ""


def _has_topic(text: str, topic: str) -> bool:
    return topic.lower() in text.lower()


def run_cross_document_checks(materials: list[ParsedMaterial]) -> list[CrossDocFinding]:
    findings: list[CrossDocFinding] = []

    by_role = {m.role: m for m in materials}
    task_book = by_role.get(ReviewPlusMaterialRole.TASK_BOOK)
    subject = by_role.get(ReviewPlusMaterialRole.SUBJECT_REPORT)
    checklist = by_role.get(ReviewPlusMaterialRole.CHECKLIST)

    if task_book and subject:
        task_text = _content(task_book)
        report_text = _content(subject)
        for topic in _KEY_TOPICS:
            in_task = _has_topic(task_text, topic)
            in_report = _has_topic(report_text, topic)
            if in_task and not in_report:
                findings.append(
                    CrossDocFinding(
                        finding_type="missing_in_report",
                        severity="major",
                        title=f"任务书提及但报告缺失：{topic}",
                        description=f"任务书涉及「{topic}」，但可靠性安全性报告未检出对应内容。",
                        doc_a=task_book.name,
                        doc_b=subject.name,
                        source_quotes=[f"任务书含 {topic}", f"报告未检出 {topic}"],
                        recommendation=f"在 {subject.name} 中补充 {topic} 相关分析或说明不适用原因。",
                    )
                )

        # 关键项目名称简单对齐：提取「关键项目」附近词组
        key_items_task = set(re.findall(r"关键项目[^\n，。；]{0,20}", task_text))
        for snippet in sorted(key_items_task)[:5]:
            keyword = snippet[-8:]
            if keyword and keyword not in report_text:
                findings.append(
                    CrossDocFinding(
                        finding_type="task_report_mismatch",
                        severity="minor",
                        title="任务书关键项目未在报告中显式出现",
                        description=f"任务书片段「{snippet}」在报告中未找到对应表述。",
                        doc_a=task_book.name,
                        doc_b=subject.name,
                        source_quotes=[snippet],
                        recommendation="核对任务书与报告对关键项目的描述是否一致。",
                    )
                )

    if checklist and subject:
        checklist_text = _content(checklist)
        report_text = _content(subject)
        for topic in ("FMEA", "FTA", "裕度", "可靠性预计"):
            if _has_topic(checklist_text, topic) and not _has_topic(report_text, topic):
                findings.append(
                    CrossDocFinding(
                        finding_type="checklist_report_gap",
                        severity="major",
                        title=f"检查单要求但报告缺失：{topic}",
                        description=f"产品保证检查单涉及 {topic}，报告未检出足够内容。",
                        doc_a=checklist.name if checklist else "",
                        doc_b=subject.name if subject else "",
                        source_quotes=[topic],
                        recommendation=f"补充 {topic} 分析或提供证据映射。",
                    )
                )

    return findings
