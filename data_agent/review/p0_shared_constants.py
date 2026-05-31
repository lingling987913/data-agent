"""Shared P0 traceability and gatekeeping constants."""

from __future__ import annotations

import re
from typing import Any

from data_agent.review.p0_schemas import MaterialItem

REQ_RE = re.compile(r"\bREQ-[A-Za-z0-9_-]+\b")
DES_RE = re.compile(r"\bDES-[A-Za-z0-9_-]+\b")
VER_RE = re.compile(r"\b(?:SIM|VER|TEST)-[A-Za-z0-9_-]+\b")

P0_GATEKEEPING_ROLE_LABELS: dict[str, str] = {
    "top_requirement": "上级需求文档",
    "decomposed_requirement": "需求分解文档",
    "design_solution": "设计方案文档",
    "interface_control": "接口控制文件",
    "simulation_report": "仿真分析报告",
    "verification_plan": "验证计划",
    "verification_result": "验证结果",
    "supporting_attachment": "支撑附件",
}

P0_ROLE_LABELS: dict[str, str] = {
    "top_requirement": "顶层需求",
    "decomposed_requirement": "分解需求",
    "design_solution": "设计方案",
    "interface_control": "接口控制",
    "simulation_report": "仿真报告",
    "verification_plan": "验证计划",
    "verification_result": "验证结果",
    "supporting_attachment": "支撑附件",
}


def material_summary(
    material: MaterialItem,
    *,
    role_labels: dict[str, str] | None = None,
) -> dict[str, Any]:
    labels = role_labels or P0_ROLE_LABELS
    return {
        "name": material.name,
        "file_type": material.file_type,
        "document_role": material.document_role,
        "document_role_label": labels.get(
            material.document_role,
            material.document_role or "未确认",
        ),
        "role_confirmed": material.role_confirmed,
        "role_confidence": material.role_confidence,
        "baseline_id": material.baseline_id,
        "document_version": material.document_version,
        "included_in_formal_review": material.included_in_formal_review,
        "parse_status": material.parse_status,
    }


def extract_inline_artifact_ids(text: str) -> list[str]:
    return list(dict.fromkeys([
        *REQ_RE.findall(text or ""),
        *DES_RE.findall(text or ""),
        *VER_RE.findall(text or ""),
    ]))
