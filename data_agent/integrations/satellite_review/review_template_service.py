"""
评审模板服务 — 加载 JSON 模板并提供查询接口

模板文件存放在 data/review_templates/ 目录下，
按 subsystem + review_phase 匹配（大小写不敏感）。

可选的活动合同侧车文档存放在 data/review_template_docs/ 目录下，
按 template_id 命名并在加载时自动合并，用于将“文档模板要求”和
“agent 活动定义/产出约束”拆开维护。

模板结构:
  - required_materials: 必需送审材料清单
  - required_sections: 必需文档章节清单
  - discipline_review_points: 各专业审查要点
  - quality_checklist: 质量师检查清单
"""

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict

from data_agent.integrations.satellite_review.rule_governance_service import validate_rule_source_refs


class RuleDefinition(BaseModel):
    model_config = ConfigDict(extra="allow")

    rule_id: str = ""
    rule_text: str = ""
    rule_type: str = "qualitative"
    severity: str = ""
    source_refs: list[Any] = []
    applicability: dict[str, Any] = {}
    version: str = ""
    status: str = ""

logger = logging.getLogger(__name__)

# 模板目录
_DEFAULT_TEMPLATE_DIR = Path(__file__).resolve().parents[3] / "data" / "review_templates"
TEMPLATES_DIR = Path(os.environ.get("AQ_REVIEW_TEMPLATE_DIR", str(_DEFAULT_TEMPLATE_DIR)))
_DEFAULT_TEMPLATE_DOCS_DIR = Path(__file__).resolve().parents[3] / "data" / "review_template_docs"
TEMPLATE_DOCS_DIR = Path(os.environ.get("AQ_REVIEW_TEMPLATE_DOCS_DIR", str(_DEFAULT_TEMPLATE_DOCS_DIR)))

# 缓存
_template_cache: Dict[str, dict] = {}
_RULE_TYPE_VALUES = {"qualitative", "quantitative", "traceability", "consistency"}
_SOURCE_REF_STRING_FIELDS = {"source_type", "source_id", "source_title", "clause", "url"}


def _extract_subsection_title(subsection: Any) -> str:
    """兼容旧字符串写法和新对象写法。"""
    if isinstance(subsection, dict):
        return str(subsection.get("title", "")).strip()
    return str(subsection or "").strip()


def _extract_section_title(section: Any) -> str:
    """兼容 required_sections 的 section/title/name 字段。"""
    if isinstance(section, dict):
        return str(
            section.get("section")
            or section.get("title")
            or section.get("name")
            or ""
        ).strip()
    return str(section or "").strip()


def _deep_merge_dict(base: dict, overlay: dict) -> dict:
    """递归合并 overlay 到 base，overlay 优先。"""
    result = dict(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge_dict(result[key], value)
        else:
            result[key] = value
    return result


def _load_template_companion(template_key: str) -> dict:
    """加载模板侧车文档（若存在）。"""
    if not template_key or not TEMPLATE_DOCS_DIR.exists():
        return {}
    companion_path = TEMPLATE_DOCS_DIR / f"{template_key}.json"
    if not companion_path.exists():
        return {}
    try:
        with open(companion_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"[ReviewTemplate] 加载模板侧车文档失败 {companion_path}: {e}")
        return {}


def get_stage_activity_contract(review_config: dict, stage_key: str) -> dict:
    """获取某个环节的活动合同定义。"""
    if not isinstance(review_config, dict):
        return {}
    contracts = review_config.get("stage_activity_contracts")
    if not isinstance(contracts, dict):
        return {}
    contract = contracts.get(stage_key)
    return contract if isinstance(contract, dict) else {}


def get_stage_contract_guidance_lines(review_config: dict, stage_key: str) -> List[str]:
    """从活动合同中提取环节说明与产出要求。"""
    contract = get_stage_activity_contract(review_config, stage_key)
    if not contract:
        return []

    lines: List[str] = []
    activity = str(contract.get("activity", "")).strip()
    summary = str(contract.get("summary", "")).strip()
    if activity and summary:
        lines.append(f"{activity}: {summary}")
    elif activity:
        lines.append(activity)
    elif summary:
        lines.append(summary)

    deliverables = contract.get("deliverables") or []
    if isinstance(deliverables, list):
        for item in deliverables:
            if isinstance(item, str) and item.strip():
                lines.append(item.strip())
            elif isinstance(item, dict):
                text = (
                    str(item.get("title", "")).strip()
                    or str(item.get("description", "")).strip()
                    or str(item.get("content", "")).strip()
                )
                if text:
                    lines.append(text)

    return lines


def get_stage_contract_rules(review_config: dict, stage_key: str) -> List[dict]:
    """从活动合同中提取审定规则列表。"""
    contract = get_stage_activity_contract(review_config, stage_key)
    if not contract:
        return []
    rules = contract.get("review_rules") or []
    if not isinstance(rules, list):
        return []
    return [normalize_rule_definition(item) for item in rules if isinstance(item, dict)]


def _normalize_source_refs(source_refs: Any) -> list[dict]:
    """收敛规则来源引用，丢弃不可审计的坏值。"""
    if not isinstance(source_refs, list):
        return []

    normalized_refs = []
    for ref in source_refs:
        if isinstance(ref, dict):
            normalized_ref = dict(ref)
            for field in _SOURCE_REF_STRING_FIELDS:
                normalized_ref[field] = str(normalized_ref.get(field, "") or "")
            normalized_refs.append(normalized_ref)
        elif isinstance(ref, str):
            normalized_refs.append({"source_id": ref})
    return normalized_refs


def normalize_rule_definition(raw: Any) -> dict:
    """规范化规则定义，同时保持旧 dict 调用兼容。"""
    if isinstance(raw, RuleDefinition):
        return raw.model_dump(mode="json")
    if not isinstance(raw, dict):
        raw = {}

    data = dict(raw)
    if "rule_text" not in data and data.get("rule_desc"):
        data["rule_text"] = data.get("rule_desc")
    if "rule_id" not in data and data.get("id"):
        data["rule_id"] = data.get("id")

    # 审查断点2：保留 required_parameters/formula/parameter_aliases/threshold/compare/unit 等 extra 字段。
    data.setdefault("rule_id", "")
    data.setdefault("rule_text", "")
    data.setdefault("rule_type", "qualitative")
    data.setdefault("severity", "")
    data.setdefault("source_refs", [])
    data.setdefault("applicability", {})
    data.setdefault("version", "")
    data.setdefault("status", "")

    data["source_refs"] = _normalize_source_refs(data.get("source_refs"))
    _validation_results = validate_rule_source_refs(data["source_refs"])
    for ref, result in zip(data["source_refs"], _validation_results):
        ref["validated"] = result["valid"]
        ref["validation_errors"] = result["errors"]

    if not isinstance(data.get("applicability"), dict):
        data["applicability"] = {}

    try:
        return RuleDefinition.model_validate(data).model_dump(mode="json")
    except Exception as e:
        logger.warning("[ReviewTemplate] 规则规范化失败，使用兼容默认值: %s", e)
        fallback = dict(data)
        fallback["rule_id"] = str(fallback.get("rule_id", "") or "")
        fallback["rule_text"] = str(fallback.get("rule_text", "") or "")
        fallback["rule_type"] = str(fallback.get("rule_type", "") or "qualitative")
        if fallback["rule_type"] not in _RULE_TYPE_VALUES:
            fallback["rule_type"] = "qualitative"
        fallback["severity"] = str(fallback.get("severity", "") or "")
        fallback["source_refs"] = _normalize_source_refs(fallback.get("source_refs"))
        _validation_results = validate_rule_source_refs(fallback["source_refs"])
        for ref, result in zip(fallback["source_refs"], _validation_results):
            ref["validated"] = result["valid"]
            ref["validation_errors"] = result["errors"]
        fallback["applicability"] = fallback.get("applicability") if isinstance(fallback.get("applicability"), dict) else {}
        fallback["version"] = str(fallback.get("version", "") or "")
        fallback["status"] = str(fallback.get("status", "") or "")
        return fallback


def _load_all_templates() -> Dict[str, dict]:
    """加载目录中所有 JSON 模板文件（懒加载 + 缓存）

    缓存 key 使用 template_id（而非 subsystem_phase），
    以支持同一 subsystem+phase 下多个模板并存（如 GNC_AD / GNC_AC / GNC_ALL）。
    """
    global _template_cache
    if _template_cache:
        return _template_cache

    if not TEMPLATES_DIR.exists():
        logger.warning(f"[ReviewTemplate] 模板目录不存在: {TEMPLATES_DIR}")
        return {}

    for fp in TEMPLATES_DIR.glob("*.json"):
        try:
            with open(fp, "r", encoding="utf-8") as f:
                tmpl = json.load(f)
            # 优先用 template_id 作 key；未设定时回退到 subsystem_phase
            key = tmpl.get("template_id") or _make_key(
                tmpl.get("subsystem", ""),
                tmpl.get("review_phase", ""),
            )
            companion = _load_template_companion(key)
            if companion:
                tmpl = _deep_merge_dict(tmpl, companion)
            _template_cache[key] = tmpl
            logger.info(
                f"[ReviewTemplate] 已加载模板: {tmpl.get('name', fp.stem)} → {key}"
            )
        except Exception as e:
            logger.warning(f"[ReviewTemplate] 加载模板失败 {fp}: {e}")

    logger.info(f"[ReviewTemplate] 共加载 {len(_template_cache)} 个模板")
    return _template_cache


def reload_templates() -> Dict[str, dict]:
    """清空缓存并重新加载模板。"""
    global _template_cache
    _template_cache = {}
    return _load_all_templates()


def list_templates() -> List[dict]:
    """列出所有可用模板的摘要信息（供前端选择器使用）"""
    templates = _load_all_templates()
    result = []
    for tmpl in templates.values():
        result.append({
            "template_id": tmpl.get("template_id", ""),
            "name": tmpl.get("name", ""),
            "subsystem": tmpl.get("subsystem", ""),
            "review_phase": tmpl.get("review_phase", ""),
            "description": tmpl.get("description", ""),
            "required_materials_count": len(tmpl.get("required_materials", [])),
            "required_sections_count": len(tmpl.get("required_sections", [])),
        })
    return result


def _make_key(subsystem: str, review_phase: str) -> str:
    return f"{subsystem.strip().upper()}_{review_phase.strip().upper()}"


def get_template(subsystem: str, review_phase: str) -> Optional[dict]:
    """按 subsystem + review_phase 获取模板。

    由于同一 subsystem+phase 可能存在多个模板（如 GNC_AD, GNC_AC, GNC_ALL），
    本方法通过遍历缓存查找第一个匹配 subsystem+phase 的模板。

    匹配优先级:
      1. 缓存 key 精确匹配 subsystem_phase（向后兼容）
      2. 遍历所有模板，找 subsystem+phase 都匹配的第一个
      3. 仅 subsystem 匹配（取第一个）
      4. None
    """
    templates = _load_all_templates()
    key = _make_key(subsystem, review_phase)

    # 1) 缓存 key 精确匹配（兼容旧的 template_id == subsystem_phase 情况）
    if key in templates:
        return templates[key]

    # 2) 遍历查找 subsystem + phase 都匹配的
    sub_upper = subsystem.strip().upper()
    phase_upper = review_phase.strip().upper()
    exact_matches = [
        tmpl for tmpl in templates.values()
        if (
            tmpl.get("subsystem", "").strip().upper() == sub_upper
            and tmpl.get("review_phase", "").strip().upper() == phase_upper
        )
    ]
    if exact_matches:
        if len(exact_matches) == 1:
            tmpl = exact_matches[0]
            logger.info(
                f"[ReviewTemplate] key={key} 未命中, 回退到 template_id={tmpl.get('template_id')}"
            )
            return tmpl

        # 无显式 template_id 时，自动匹配必须稳定且可预期。
        preferred = next(
            (
                tmpl for tmpl in exact_matches
                if (tmpl.get("review_scope", "") or "").strip().lower() == "ad_ac"
            ),
            None,
        )
        if preferred:
            logger.info(
                "[ReviewTemplate] key=%s 未命中, 多模板场景默认选用联合模板 template_id=%s",
                key,
                preferred.get("template_id"),
            )
            return preferred

        exact_matches.sort(key=lambda tmpl: str(tmpl.get("template_id", "")))
        fallback = exact_matches[0]
        logger.warning(
            "[ReviewTemplate] key=%s 存在多个候选模板且无联合模板, 回退到 template_id=%s",
            key,
            fallback.get("template_id"),
        )
        return fallback

    # 3) 仅 subsystem 模糊匹配
    for tmpl in templates.values():
        if tmpl.get("subsystem", "").strip().upper() == sub_upper:
            logger.info(
                f"[ReviewTemplate] subsystem 模糊匹配: {tmpl.get('template_id')}"
            )
            return tmpl

    logger.info(f"[ReviewTemplate] 未找到模板: {key}")
    return None


def resolve_template(
    subsystem: str,
    review_phase: str,
    template_id: str = "",
) -> Optional[dict]:
    """优先按 template_id 解析模板，未提供时回退到 subsystem + review_phase。"""
    if template_id:
        tmpl = get_template_by_id(template_id)
        if tmpl:
            return tmpl
        logger.info(
            f"[ReviewTemplate] template_id={template_id} 未命中，回退 subsystem/phase"
        )
    return get_template(subsystem, review_phase)


def get_template_by_id(template_id: str) -> Optional[dict]:
    """按 template_id 获取模板。

    由于缓存 key 现在就是 template_id，可以直接查找。
    支持旧 template_id 的向后兼容别名（如 GNC_CDR → GNC_ALL）。
    """
    if not template_id:
        return None

    # ── 向后兼容别名 ──
    _LEGACY_ALIASES: Dict[str, str] = {
        "GNC_CDR": "GNC_ALL",
    }
    resolved_id = _LEGACY_ALIASES.get(template_id, template_id)
    if resolved_id != template_id:
        logger.info(
            f"[ReviewTemplate] 旧 template_id={template_id} 映射到 {resolved_id}"
        )

    templates = _load_all_templates()
    # 直接查缓存 key
    if resolved_id in templates:
        return templates[resolved_id]
    # 兼容: 扫描 template_id 字段
    for tmpl in templates.values():
        if tmpl.get("template_id") == resolved_id:
            return tmpl
    logger.info(f"[ReviewTemplate] 未找到 template_id={template_id}")
    return None


def get_required_materials(template: dict) -> List[dict]:
    """获取必需材料清单"""
    return template.get("required_materials", [])


def get_required_sections(template: dict) -> List[dict]:
    """获取必需章节清单"""
    return template.get("required_sections", [])


def get_quality_checklist(template: dict) -> List[str]:
    """获取质量师检查清单"""
    return template.get("quality_checklist", [])


def get_discipline_points(template: dict, discipline: str) -> dict:
    """获取指定专业的审查要点"""
    points = template.get("discipline_review_points", {})
    return points.get(discipline, {})


def get_ad_review_config(template: dict) -> dict:
    """获取 AD 专业组动态审查配置。"""
    return template.get("ad_review", {})


def format_quality_prompt_section(template: dict) -> str:
    """
    将模板的质量审查要求格式化为可插入 LLM prompt 的文本段。
    包含: 必需材料清单 + 必需章节清单 + 质量检查项。
    """
    lines = []
    name = template.get("name", "评审模板")
    lines.append(f"## 当前评审模板: {name}\n")

    # 必需材料
    mats = get_required_materials(template)
    if mats:
        lines.append("### 必需送审材料")
        for m in mats:
            req = "【必需】" if m.get("required") else "【可选】"
            lines.append(f"- {req} {m['name']}: {m.get('description', '')}")
        lines.append("")

    # 必需章节
    secs = get_required_sections(template)
    if secs:
        lines.append("### 必需文档章节")
        for s in secs:
            req = "【必需】" if s.get("required") else "【可选】"
            lines.append(f"- {req} {_extract_section_title(s)}: {s.get('description', '')}")
        lines.append("")

    # 质量检查项
    checklist = get_quality_checklist(template)
    if checklist:
        lines.append("### 质量检查项")
        for i, item in enumerate(checklist, 1):
            lines.append(f"- [{i}] {item}")
        lines.append("")

    return "\n".join(lines)


def format_discipline_prompt_section(
    template: dict, discipline: str
) -> str:
    """
    将指定专业的审查要点格式化为可插入 Agent prompt 的文本段。
    """
    dp = get_discipline_points(template, discipline)
    if not dp:
        return ""

    lines = [
        f"## 本次评审模板审查要点 — {dp.get('discipline_name', discipline)}",
        "",
        "请逐项检查以下审查要点，对每项给出审查发现:",
        "",
    ]
    for i, item in enumerate(dp.get("checklist", []), 1):
        lines.append(f"  {i}. {item}")
    lines.append("")
    return "\n".join(lines)


def list_templates() -> List[dict]:
    """列出所有可用模板（摘要信息）"""
    templates = _load_all_templates()
    result = []
    for tmpl in templates.values():
        result.append({
            "template_id": tmpl.get("template_id", ""),
            "name": tmpl.get("name", ""),
            "subsystem": tmpl.get("subsystem", ""),
            "review_phase": tmpl.get("review_phase", ""),
            "description": tmpl.get("description", ""),
            "required_materials_count": len(tmpl.get("required_materials", [])),
            "required_sections_count": len(tmpl.get("required_sections", [])),
        })
    return result


def build_unit_specs(template: dict, review_scope: str = "ad_ac") -> list[dict]:
    """从现有 JSON 模板中组装单元审查规格 (UnitSpec)。

    返回统一格式:
      [{
          "unit_key": "ad_req_err",
          "unit_name": "姿态确定需求确认与误差分解",
          "required_titles": ["姿态确定需求确认与误差分解", ...],
          "alias_titles": ["需求确认", "误差分解", ...],
          "subsection_titles": ["姿态确定技术要求", ...],
          "min_text_length": 200,
          "rules": [...],
      }]
    """
    specs = []

    # 从 required_sections 提取章节映射
    required_sections = template.get("required_sections", [])
    section_map = {}  # stage_index -> {section, subsections, required}
    for i, sec in enumerate(required_sections):
        section_text = _extract_section_title(sec)
        # 去掉编号前缀, 如 "1 姿态确定..." -> "姿态确定..."
        clean_title = section_text.strip()
        parts = clean_title.split(" ", 1)
        if len(parts) > 1 and parts[0].replace(".", "").isdigit():
            clean_title = parts[1].strip()

        subsections = sec.get("subsections", [])
        clean_subs = []
        for sub in subsections:
            sub_title = _extract_subsection_title(sub)
            sub_parts = sub_title.split(" ", 1)
            if len(sub_parts) > 1 and sub_parts[0].replace(".", "").isdigit():
                clean_subs.append(sub_parts[1].strip())
            else:
                clean_subs.append(sub_title)

        section_map[i] = {
            "title": clean_title,
            "original": section_text,
            "subsections": clean_subs,
            "required": sec.get("required", False),
        }

    # 根据 review_scope 决定加载哪些配置
    review_keys = []
    if review_scope in ("ad_only", "ad_ac"):
        review_keys.append("ad_review")
    if review_scope in ("ac_only", "ad_ac"):
        review_keys.append("ac_review")

    # 从 ad_review/ac_review 提取单元规则定义
    for review_key in review_keys:
        review_config = template.get(review_key, {})
        if not review_config:
            continue

        if isinstance(review_config.get("stage_activity_contracts"), dict) and review_config.get("stage_activity_contracts"):
            stage_rule_specs = {
                stage_key: get_stage_contract_rules(review_config, stage_key)
                for stage_key in (review_config.get("stage_activity_contracts", {}) or {}).keys()
            }
            stage_guidance = {
                stage_key: get_stage_contract_guidance_lines(review_config, stage_key)
                for stage_key in (review_config.get("stage_activity_contracts", {}) or {}).keys()
            }
        else:
            stage_rule_specs = {
                stage_key: [
                    normalize_rule_definition(item)
                    for item in (rules or [])
                    if isinstance(item, dict)
                ]
                for stage_key, rules in (review_config.get("stage_rule_specs", {}) or {}).items()
            }
            stage_guidance = review_config.get("stage_guidance", {})
        prefix = "ad" if review_key == "ad_review" else "ac"

        # stage_key -> 章节映射 (通过关键词匹配 required_sections)
        _STAGE_SECTION_KEYWORDS = _get_stage_section_keywords(prefix)

        for stage_key, rules in stage_rule_specs.items():
            unit_key = f"{prefix}_{stage_key}"
            unit_name = _get_unit_name(prefix, stage_key)

            # 查找关联的 required_sections
            required_titles = []
            alias_titles = []
            subsection_titles = []
            keywords = _STAGE_SECTION_KEYWORDS.get(stage_key, [])

            for _idx, sec_info in section_map.items():
                if any(kw in sec_info["title"] or kw in sec_info["original"] for kw in keywords):
                    required_titles.append(sec_info["title"])
                    alias_titles.extend(keywords)
                    subsection_titles.extend(sec_info["subsections"])

            # 去重
            required_titles = list(dict.fromkeys(required_titles))
            alias_titles = list(dict.fromkeys(alias_titles))
            subsection_titles = list(dict.fromkeys(subsection_titles))

            specs.append({
                "unit_key": unit_key,
                "unit_name": unit_name,
                "required_titles": required_titles,
                "alias_titles": alias_titles,
                "keyword_backfill": list(alias_titles),
                "subsection_titles": subsection_titles,
                "min_text_length": 200,
                "rules": rules,
                "guidance": stage_guidance.get(stage_key, []),
            })

    logger.info(f"[ReviewTemplate] 组装了 {len(specs)} 个 UnitSpec")
    return specs


def _get_stage_section_keywords(prefix: str) -> dict[str, list[str]]:
    """获取阶段与章节标题的关键词映射。"""
    if prefix == "ad":
        return {
            "req_err": ["需求", "误差分解", "误差预算", "姿态确定需求"],
            "timing": ["时序", "采集时序", "同步"],
            "install": ["安装指向", "测量单机安装", "安装设计"],
            "algorithm": ["算法设计", "姿态确定算法", "滤波算法", "融合"],
            "simulation": ["仿真", "数学仿真", "结果分析"],
        }
    else:  # ac
        return {
            "req_err": ["需求", "误差分解", "误差预算", "控制指标", "姿态控制技术要求", "执行机构能力"],
            "thruster_layout": ["推力器布局", "推力器布置", "喷口"],
            "other_actuator_layout": ["执行机构布局", "飞轮", "磁力矩器", "CMG"],
            "control_law": ["控制律", "控制架构", "稳定性", "鲁棒性"],
            "control_params": ["参数设计", "参数整定", "控制参数"],
            "maneuver_law": ["操纵律", "机动律", "姿态机动"],
            "unloading_law": ["卸载律", "动量卸载", "角动量"],
            "simulation": ["姿控仿真", "闭环仿真", "控制仿真"],
        }


def _get_unit_name(prefix: str, stage_key: str) -> str:
    """获取单元中文名称。"""
    _NAMES = {
        "ad_req_err": "姿态确定需求确认与误差分解",
        "ad_timing": "采集时序设计",
        "ad_install": "姿态测量单机安装指向设计",
        "ad_algorithm": "姿态确定算法设计",
        "ad_simulation": "姿态确定数学仿真与结果分析",
        "ac_req_err": "需求确认与误差分解",
        "ac_thruster_layout": "推力器布局",
        "ac_other_actuator_layout": "执行机构布局",
        "ac_control_law": "控制律设计",
        "ac_control_params": "姿控参数设计",
        "ac_maneuver_law": "操纵律设计",
        "ac_unloading_law": "卸载律设计",
        "ac_simulation": "姿控仿真",
    }
    return _NAMES.get(f"{prefix}_{stage_key}", stage_key)
