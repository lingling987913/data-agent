"""
模板结构准入服务 (Template Gatekeeping Service)

硬规则门禁 — 不依赖 LLM，基于单元配置对章节树执行通过/失败判定。

判定规则:
  - 缺失一级主章节 → hard_fail (阻断该单元进入专业深审)
  - 有章节但正文 < min_text_length → soft_fail (标记风险但放行)
  - 缺少子章节 → soft_fail (标记但不阻断)
  - 标题不标准但关键词命中 → pass_with_note
  - 正常 → pass
"""

import logging
from typing import Optional

from data_agent.parsing.schemas import (
    DocumentSection,
    DocumentSectionTree,
    TemplateGatekeepingResult,
)
from data_agent.integrations.satellite_review.review_template_service import build_unit_specs

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════
#  单元配置提取
# ══════════════════════════════════════════════


def extract_unit_specs_from_template(template: dict, review_scope: str = "ad_ac") -> list[dict]:
    """向后兼容别名：委托给 template_service.build_unit_specs"""
    return build_unit_specs(template, review_scope=review_scope)


# ══════════════════════════════════════════════
#  模板结构准入执行
# ══════════════════════════════════════════════


def _match_sections_for_unit(
    unit_spec: dict,
    section_tree: DocumentSectionTree,
) -> list[DocumentSection]:
    """为指定单元在章节树中查找命中章节。

    匹配优先级:
      1. required_titles 精确包含匹配
      2. alias_titles 模糊匹配
    """
    matched, _ = _match_sections_for_unit_with_mode(unit_spec, section_tree)
    return matched


def _match_sections_for_unit_with_mode(
    unit_spec: dict,
    section_tree: DocumentSectionTree,
) -> tuple[list[DocumentSection], str]:
    required_titles = unit_spec.get("required_titles", [])
    alias_titles = unit_spec.get("alias_titles", [])
    keyword_backfill = unit_spec.get("keyword_backfill", [])
    matched: list[DocumentSection] = []
    matched_ids: set[str] = set()
    match_mode = ""

    for section in section_tree.sections:
        s_title = section.title.strip()
        s_text = section.text.strip()
        if not s_title:
            continue

        # 精确标题匹配
        for rt in required_titles:
            if rt in s_title or s_title in rt:
                if section.section_id not in matched_ids:
                    matched.append(section)
                    matched_ids.add(section.section_id)
                    match_mode = match_mode or "required"
                break

        # 别名匹配
        if section.section_id not in matched_ids:
            for alias in alias_titles:
                if alias and alias in s_title:
                    if section.section_id not in matched_ids:
                        matched.append(section)
                        matched_ids.add(section.section_id)
                        match_mode = match_mode or "alias"
                    break

        # 关键词回补: 允许标题或章节正文命中
        if section.section_id not in matched_ids:
            for keyword in keyword_backfill:
                if keyword and (keyword in s_title or keyword in s_text):
                    matched.append(section)
                    matched_ids.add(section.section_id)
                    match_mode = match_mode or "keyword_backfill"
                    break

    return matched, (match_mode or "none")


def _check_subsections(
    unit_spec: dict,
    matched_sections: list[DocumentSection],
    section_tree: DocumentSectionTree,
) -> list[str]:
    """检查子章节覆盖情况, 返回缺失子章节的提示列表。"""
    subsection_titles = unit_spec.get("subsection_titles", [])
    if not subsection_titles:
        return []

    # 收集命中章节的子章节标题
    child_titles: set[str] = set()
    all_sections_by_id = {s.section_id: s for s in section_tree.sections}
    for sec in matched_sections:
        for child_id in sec.children_ids:
            child = all_sections_by_id.get(child_id)
            if child:
                child_titles.add(child.title.strip())

    missing = []
    for expected in subsection_titles:
        found = any(expected in ct or ct in expected for ct in child_titles)
        if not found:
            missing.append(expected)

    return missing


def run_template_gatekeeping(
    section_tree: DocumentSectionTree,
    unit_specs: list[dict],
) -> list[TemplateGatekeepingResult]:
    """对每个审查单元执行模板结构准入检查。

    判定规则:
      - 无命中章节 → hard_fail
      - 有章节但正文 < min_text_length → soft_fail
      - 缺少子章节 → soft_fail
      - 标题不标准但关键词命中 → pass_with_note
      - 正常 → pass
    """
    results: list[TemplateGatekeepingResult] = []

    for spec in unit_specs:
        unit_key = spec["unit_key"]
        unit_name = spec.get("unit_name", unit_key)
        min_text_length = spec.get("min_text_length", 200)

        matched, match_mode = _match_sections_for_unit_with_mode(spec, section_tree)

        if not matched:
            results.append(TemplateGatekeepingResult(
                unit_key=unit_key,
                unit_name=unit_name,
                status="hard_fail",
                issues=[f"缺失主章节: {', '.join(spec.get('required_titles', [])[:3])}"],
                summary=f"未在文档中找到 {unit_name} 对应章节，不能进入专业审查。",
            ))
            continue

        matched_ids = [s.section_id for s in matched]
        total_length = sum(len(s.text) for s in matched)
        issues: list[str] = []

        # 检查正文长度
        if total_length < min_text_length:
            issues.append(f"正文长度不足: {total_length} 字 (最低 {min_text_length})")

        # 检查子章节
        missing_subs = _check_subsections(spec, matched, section_tree)
        if missing_subs:
            issues.append(f"缺少子章节: {', '.join(missing_subs[:3])}")

        # 判定状态
        if total_length < min_text_length:
            status = "soft_fail"
            summary = f"{unit_name} 章节存在，但正文长度不足（{total_length} 字）。"
        elif missing_subs:
            status = "soft_fail"
            summary = f"{unit_name} 主章节存在，但有 {len(missing_subs)} 个子章节未找到。"
        else:
            if match_mode == "required":
                status = "pass"
                summary = f"{unit_name} 结构完整，可进入专业审查。"
            else:
                status = "pass_with_note"
                if match_mode == "alias":
                    summary = f"{unit_name} 通过别名标题识别到等价章节，建议核实标题规范性。"
                else:
                    summary = f"{unit_name} 通过关键词回补识别到等价章节，建议核实标题规范性。"

        results.append(TemplateGatekeepingResult(
            unit_key=unit_key,
            unit_name=unit_name,
            status=status,
            matched_section_ids=matched_ids,
            total_text_length=total_length,
            issues=issues,
            summary=summary,
        ))

    # 统计日志
    hard_fails = sum(1 for r in results if r.status == "hard_fail")
    soft_fails = sum(1 for r in results if r.status == "soft_fail")
    passes = sum(1 for r in results if r.status in ("pass", "pass_with_note"))
    logger.info(
        f"[Gatekeeping] 准入完成: {len(results)} 个单元, "
        f"pass={passes}, soft_fail={soft_fails}, hard_fail={hard_fails}"
    )

    return results
