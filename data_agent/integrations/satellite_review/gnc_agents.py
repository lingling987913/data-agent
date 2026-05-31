"""Agno Agent definitions for the satellite GNC design review committee."""

from __future__ import annotations

import os
import json
import re
from pathlib import Path
from typing import Any

try:
    from agno.agent import Agent
except ModuleNotFoundError:  # pragma: no cover - import compatibility for minimal test envs
    class Agent:  # type: ignore[no-redef]
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            raise ModuleNotFoundError("agno is required to instantiate GNC review agents")

from data_agent.integrations.satellite_review.gnc_schemas import (
    GNCChiefDecisionOutput,
    GNCCommitteeOutput,
    GNCEditorialOutput,
)


def _knowledge_root() -> Path:
    return Path(os.getenv("GNC_KNOWLEDGE_DIR") or Path(__file__).resolve().parents[3] / "data" / "knowledge" / "gnc")


def _tokenize_query(query: str) -> list[str]:
    tokens = re.findall(r"[A-Za-z0-9_-]+|[\u4e00-\u9fff]{2,}", query or "")
    return [token.lower() for token in tokens if token.strip()]


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            out.append(item)
    return out


def _search_local_knowledge(kind: str, query: str, *, top_k: int = 5) -> dict[str, Any]:
    root = _knowledge_root()
    path = root / f"{kind}.jsonl"
    items = _load_jsonl(path)
    if not items:
        return {
            "source": kind,
            "query": query,
            "status": "degraded",
            "items": [],
            "note": f"Local GNC knowledge file not found or empty: {path}",
        }
    tokens = _tokenize_query(query)
    scored = []
    for item in items:
        haystack = " ".join(
            str(item.get(key, ""))
            for key in ("id", "title", "category", "content", "source", "severity")
        ).lower()
        haystack += " " + " ".join(str(tag).lower() for tag in item.get("tags", []) or [])
        score = sum(1 for token in tokens if token and token in haystack)
        if not tokens:
            score = 1
        if score:
            scored.append((score, item))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return {
        "source": kind,
        "query": query,
        "status": "ok",
        "items": [
            {
                "id": item.get("id", ""),
                "title": item.get("title", ""),
                "category": item.get("category", ""),
                "content": item.get("content", ""),
                "source": item.get("source", ""),
                "severity": item.get("severity", ""),
                "tags": item.get("tags", []),
                "score": score,
            }
            for score, item in scored[:top_k]
        ],
        "note": f"Local keyword retrieval from {path}",
    }


def search_gnc_standards(query: str) -> dict[str, Any]:
    """Search local GNC standard clauses as tool-visible evidence."""
    return _search_local_knowledge("standards", query)


def search_review_knowledge(query: str) -> dict[str, Any]:
    """Search local GNC review experience notes as tool-visible evidence."""
    return _search_local_knowledge("review_knowledge", query)


def query_interface_graph(query: str) -> dict[str, Any]:
    """Search local interface relation records as tool-visible evidence."""
    return _search_local_knowledge("interface_graph", query)


def _structured_agent_kwargs(
    *,
    output_schema: type,
    instructions: list[str],
    tools: list[Any] | None = None,
    model_id: str | None = None,
    **agent_kwargs: Any,
) -> dict[str, Any]:
    from data_agent.agno_structured import build_agent_kwargs, probe_provider_capabilities

    cap = probe_provider_capabilities(role="general")
    return build_agent_kwargs(
        cap,
        output_schema=output_schema,
        instructions=instructions,
        tools=tools,
        model_id=model_id or os.getenv("GNC_REVIEW_LLM_MODEL_ID") or None,
        **agent_kwargs,
    )


def _base_output_rules() -> list[str]:
    return [
        "输出必须符合给定的 Pydantic output_schema。",
        "只基于送审文档、审查规则和工具返回依据形成知识型审查意见。",
        "不得声称已经完成算法验证、仿真执行、试验确认或数值复算。",
        "每条 finding 必须写明 evidence_ids 或 source_quotes；依据不足时 judgment=insufficient_evidence。",
        "严重度仅使用 critical / major / minor / suggestion / info。",
    ]


def gnc_chief_reviewer(model_id: str | None = None, *, debug_mode: bool = False) -> Agent:
    return Agent(**_structured_agent_kwargs(
        id="aero:gnc_chief_reviewer",
        name="GNC 总师",
        role="GNC 知识型审查统筹与最终审定",
        output_schema=GNCChiefDecisionOutput,
        instructions=[
            "你是 GNC 设计方案评审委员会总师，负责统筹专家意见、裁决冲突并给出审定结论。",
            "你的结论建立在 Findings、Evidence、审查规则和合稿清单上。",
            "若知识依据不足、专家意见相左且证据优先级无法裁决，必须 requires_arbitration=true。",
            "裁决优先级: 确定性预检/结构化证据 > 直接文档证据 > 明确审查规则 > 专家语义判断。",
            *_base_output_rules(),
        ],
        tools=[search_gnc_standards, search_review_knowledge],
        debug_mode=debug_mode,
        model_id=model_id,
    ))


def fdir_specialist(model_id: str | None = None, *, debug_mode: bool = False) -> Agent:
    return Agent(**_structured_agent_kwargs(
        id="aero:fdir_specialist",
        name="FDIR 专家",
        role="故障检测、隔离与恢复设计说明知识型审查",
        output_schema=GNCCommitteeOutput,
        instructions=[
            "你是 FDIR 领域知识型审查专家。",
            "重点审查故障场景覆盖、检测-隔离-恢复链条、安全模式、单点/共因故障控制说明。",
            "识别历史故障处置经验中常见遗漏，但不得替代设计方执行 FMEA/FMECA。",
            *_base_output_rules(),
        ],
        tools=[search_gnc_standards, search_review_knowledge, query_interface_graph],
        debug_mode=debug_mode,
        model_id=model_id,
    ))


def interface_specialist(model_id: str | None = None, *, debug_mode: bool = False) -> Agent:
    return Agent(**_structured_agent_kwargs(
        id="aero:interface_specialist",
        name="接口协调专家",
        role="GNC 跨分系统接口一致性知识型审查",
        output_schema=GNCCommitteeOutput,
        instructions=[
            "你是系统集成与接口管理专家。",
            "重点审查 ICD 完整性、数据刷新率/总线/协议/时延、功耗热控推进载荷接口约束、跨文档参数映射。",
            "multi_doc 模式下必须检查不同文档对同一接口、版本、参数、单位的矛盾。",
            *_base_output_rules(),
        ],
        tools=[search_review_knowledge, query_interface_graph, search_gnc_standards],
        debug_mode=debug_mode,
        model_id=model_id,
    ))


def quality_engineer(model_id: str | None = None, *, debug_mode: bool = False) -> Agent:
    return Agent(**_structured_agent_kwargs(
        id="aero:quality_engineer",
        name="质量师",
        role="送审材料质量与可审查性判定",
        output_schema=GNCCommitteeOutput,
        instructions=[
            "你是 GNC 设计评审质量师，只判断材料是否达到可审查状态。",
            "重点审查材料齐套性、体例规范、术语编号引用一致性、需求-设计-验证叙述可对应性。",
            "不评价技术正确性；材料不足会阻塞专业审查时必须明确指出。",
            *_base_output_rules(),
        ],
        tools=[search_gnc_standards, search_review_knowledge],
        debug_mode=debug_mode,
        model_id=model_id,
    ))


def review_editor(model_id: str | None = None, *, debug_mode: bool = False) -> Agent:
    return Agent(**_structured_agent_kwargs(
        id="aero:review_editor",
        name="合稿师",
        role="Findings 归并、RID 编制与评审纪要成稿",
        output_schema=GNCEditorialOutput,
        instructions=[
            "你是 GNC 设计评审合稿师，负责将专家 Findings 归并为 RID、纪要和结论草案。",
            "你负责写，不负责最终裁定；不得删除专家原始分歧。",
            "RID 必须保留关联 finding_id、evidence_id、严重度、影响分析和建议措施。",
        ],
        tools=[search_review_knowledge],
        debug_mode=debug_mode,
        model_id=model_id,
    ))


def simulation_specialist(model_id: str | None = None, *, debug_mode: bool = False) -> Agent:
    return Agent(**_structured_agent_kwargs(
        id="aero:simulation_specialist",
        name="验证审查专家",
        role="验证方案充分性知识型审查",
        output_schema=GNCCommitteeOutput,
        instructions=[
            "你是验证与确认领域的知识型审查专家。",
            "重点审查验证矩阵、正常/最恶劣/故障注入/模式切换工况覆盖、统计验证说明和验证结果支撑性。",
            "不执行仿真，不产出仿真结果，不自行复算关键数值。",
            *_base_output_rules(),
        ],
        tools=[search_gnc_standards, search_review_knowledge],
        debug_mode=debug_mode,
        model_id=model_id,
    ))


def build_unit_agent(
    unit_id: str,
    unit_payload: dict[str, Any],
    model_id: str | None = None,
    *,
    debug_mode: bool = False,
) -> Agent:
    """Build a generic AD/AC review-unit Agent from its registry profile.

    Instructions are derived from the unit's role/triggers so all 17 units share
    one builder; output conforms to ``GNCCommitteeOutput`` like the horizontal
    committee experts.
    """
    unit_name = str(unit_payload.get("name") or unit_id)
    unit_role = str(unit_payload.get("role") or "")
    unit_group = str(unit_payload.get("unit_group") or "").upper()
    triggers = [str(item) for item in (unit_payload.get("triggers") or []) if str(item) != "all"]
    return Agent(**_structured_agent_kwargs(
        id=f"aero:{unit_id}",
        name=unit_name,
        role=unit_role or f"{unit_group} 专业审查单元",
        output_schema=GNCCommitteeOutput,
        instructions=[
            f"你是 GNC {unit_group} 专业组的「{unit_name}」审查单元。",
            f"审查职责: {unit_role}",
            f"关注的专业信号: {', '.join(triggers[:10])}。",
            "只针对本单元职责范围形成知识型审查发现，不越界评判其他单元的设计内容。",
            *_base_output_rules(),
        ],
        tools=[search_gnc_standards, search_review_knowledge],
        debug_mode=debug_mode,
        model_id=model_id,
    ))


COMMITTEE_AGENT_BUILDERS = {
    "quality_engineer": quality_engineer,
    "fdir_specialist": fdir_specialist,
    "interface_specialist": interface_specialist,
    "simulation_specialist": simulation_specialist,
}


__all__ = [
    "COMMITTEE_AGENT_BUILDERS",
    "build_unit_agent",
    "fdir_specialist",
    "gnc_chief_reviewer",
    "interface_specialist",
    "quality_engineer",
    "review_editor",
    "simulation_specialist",
]
