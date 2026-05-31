"""Deterministic role hints for controlled review materials."""

from __future__ import annotations

from dataclasses import dataclass


SUPPORTED_DOCUMENT_ROLES = (
    "top_requirement",
    "decomposed_requirement",
    "design_solution",
    "interface_control",
    "simulation_report",
    "verification_plan",
    "verification_result",
    "supporting_attachment",
)


@dataclass(frozen=True)
class MaterialRoleSuggestion:
    document_role: str
    confidence: float
    reason: str


_ROLE_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("top_requirement", ("任务书", "总体技术要求", "上级需求", "top requirement", "REQ-TOP")),
    ("decomposed_requirement", ("分系统需求", "专业需求", "需求分解", "decomposed", "REQ-GNC")),
    ("design_solution", ("方案设计", "设计方案", "算法设计", "控制律", "design solution", "DES-")),
    ("interface_control", ("接口控制", "ICD", "接口文件", "坐标系", "interface control")),
    ("simulation_report", ("仿真", "仿真分析", "蒙特卡洛", "simulation", "SIM-")),
    ("verification_plan", ("验证计划", "试验计划", "verification plan", "验证矩阵")),
    ("verification_result", ("验证结果", "试验报告", "测试报告", "verification result", "通过", "未通过")),
)


def infer_material_role(name: str, content: str = "", file_type: str = "") -> MaterialRoleSuggestion:
    sample = f"{name}\n{file_type}\n{(content or '')[:4000]}".lower()
    best_role = "supporting_attachment"
    best_score = 0
    best_hits: list[str] = []

    for role, hints in _ROLE_HINTS:
        hits = [hint for hint in hints if hint.lower() in sample]
        score = len(hits)
        if score > best_score:
            best_role = role
            best_score = score
            best_hits = hits

    if best_score == 0:
        return MaterialRoleSuggestion(
            document_role="supporting_attachment",
            confidence=0.35,
            reason="未命中 P0 文档角色关键词，按支撑附件处理",
        )

    confidence = min(0.95, 0.55 + best_score * 0.12)
    return MaterialRoleSuggestion(
        document_role=best_role,
        confidence=round(confidence, 2),
        reason=f"命中角色关键词: {', '.join(best_hits[:4])}",
    )
