"""Rule-based engineering object extraction for review bundles."""

from __future__ import annotations

import re
import uuid

from data_agent.parsing.schemas import (
    DesignElement,
    DocumentEvidence,
    ExtractedParameter,
    ExtractedTechnicalObject,
    RequirementItem,
    ReviewDocumentBundle,
    TraceLinkCandidate,
    TraceabilityMatrixSummary,
    VerificationItem,
)

_TRACE_ID_RE = re.compile(r"\b((?:REQ|DES|SIM|VER|TEST|VAL|CHECK|CHK)-[A-Z0-9][A-Z0-9_-]*)\b", re.I)
_PARAM_RE = re.compile(
    r"(?P<name>姿态确定精度|角速率确定精度|姿态控制稳态误差|稳态误差|机动时间|推力偏差|检测时间|保持精度|指向精度|驱动力矩裕度|控制周期|遥测下传周期|刷新率|更新频率|时延|带宽|阈值)"
    r"[^。\n，,；;]{0,40}?"
    r"(?P<comparator>不大于|不小于|小于|大于|≤|>=|≥|<=|=|约|为)?\s*"
    r"(?P<value>[+-]?\d+(?:\.\d+)?)\s*"
    r"(?P<unit>deg/s|deg/h|deg|ms|s|Hz|N|Nm|%|倍)?",
    re.I,
)
_OBJECT_KEYWORDS = {
    "star_sensor": ("星敏", "星敏感器"),
    "gyro": ("陀螺", "光纤陀螺"),
    "reaction_wheel": ("反作用飞轮", "飞轮"),
    "thruster": ("推力器", "推力"),
    "magnetorquer": ("磁力矩器", "磁控"),
    "sada": ("SADA", "太阳翼驱动"),
    "bus": ("1553B", "总线"),
    "fdir": ("FDIR", "故障检测", "故障隔离", "恢复"),
}


def _clip_text(text: str, limit: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[:limit] + "..."


def _normalize_comparator(value: str) -> str:
    mapping = {
        "不大于": "<=",
        "小于": "<",
        "≤": "<=",
        "<=": "<=",
        "不小于": ">=",
        "大于": ">",
        "≥": ">=",
        ">=": ">=",
        "=": "=",
        "为": "=",
        "约": "~",
    }
    return mapping.get((value or "").strip(), "")


def _gnc_context_tags(text: str) -> list[str]:
    tags = []
    tag_keywords = {
        "attitude_determination": ("姿态确定", "星敏", "陀螺", "导航"),
        "attitude_control": ("姿态控制", "控制律", "稳态误差", "机动"),
        "orbit_control": ("轨道", "推力", "推力器"),
        "fdir": ("故障", "FDIR", "隔离", "恢复", "安全模式"),
        "interface": ("接口", "总线", "刷新率", "周期", "ICD"),
        "verification": ("仿真", "试验", "验证", "矩阵"),
    }
    for tag, keywords in tag_keywords.items():
        if any(keyword.lower() in text.lower() for keyword in keywords):
            tags.append(tag)
    return tags


def _extract_parameters_from_text(
    text: str,
    evidence: DocumentEvidence,
    context_tags: list[str],
) -> list[ExtractedParameter]:
    out = []
    for match in _PARAM_RE.finditer(text):
        raw_value = match.group("value")
        name = match.group("name")
        unit = match.group("unit") or ""
        comparator = _normalize_comparator(match.group("comparator") or "")
        out.append(
            ExtractedParameter(
                parameter_id=f"param-{str(uuid.uuid4())[:8]}",
                name=name,
                normalized_name=re.sub(r"\s+", "", name).lower(),
                value=float(raw_value),
                raw_value=f"{match.group('comparator') or ''}{raw_value}{unit}",
                unit=unit,
                comparator=comparator,
                source_section_id=evidence.section_id,
                source_evidence_id=evidence.evidence_id,
                block_ids=list(evidence.block_ids),
                source_text=_clip_text(text, 500),
                confidence=0.55 if unit else 0.4,
                context_tags=context_tags,
            )
        )
    return out


def _extract_objects_from_text(text: str, evidence: DocumentEvidence) -> list[ExtractedTechnicalObject]:
    out = []
    haystack = text.lower()
    for object_type, keywords in _OBJECT_KEYWORDS.items():
        for keyword in keywords:
            if keyword.lower() not in haystack:
                continue
            out.append(
                ExtractedTechnicalObject(
                    object_id=f"obj-{str(uuid.uuid4())[:8]}",
                    name=keyword,
                    normalized_name=keyword.lower(),
                    object_type=object_type,
                    source_section_id=evidence.section_id,
                    source_evidence_id=evidence.evidence_id,
                    block_ids=list(evidence.block_ids),
                    source_text=_clip_text(text, 500),
                    confidence=0.45,
                )
            )
            break
    return out


def _extract_trace_ids(text: str) -> dict[str, list[str]]:
    ids = list(dict.fromkeys(match.group(1).upper() for match in _TRACE_ID_RE.finditer(text)))
    return {
        "requirements": [item for item in ids if item.startswith("REQ-") or item.startswith(("CHECK-", "CHK-"))],
        "designs": [item for item in ids if item.startswith("DES-")],
        "verifications": [item for item in ids if item.startswith(("SIM-", "VER-", "TEST-", "VAL-"))],
    }


def _infer_verification_method(text: str) -> str:
    if "仿真" in text or "SIM-" in text:
        return "simulation"
    if "试验" in text or "测试" in text or "TEST-" in text:
        return "test"
    if "检查" in text or "校核" in text:
        return "inspection"
    return "analysis"


def _trace_candidate(
    source_id: str,
    target_id: str,
    link_type: str,
    evidence: DocumentEvidence,
    text: str,
) -> TraceLinkCandidate:
    return TraceLinkCandidate(
        link_id=f"link-{str(uuid.uuid4())[:8]}",
        source_id=source_id,
        target_id=target_id,
        link_type=link_type,
        source_section_id=evidence.section_id,
        source_evidence_id=evidence.evidence_id,
        block_ids=list(evidence.block_ids),
        source_text=_clip_text(text, 500),
        confidence=0.5,
    )


def attach_extracted_structured_objects(bundle: ReviewDocumentBundle) -> None:
    """Attach lightweight rule-based engineering extraction results to bundle."""
    parameters_by_key: dict[tuple[str, str], ExtractedParameter] = {}
    objects_by_key: dict[tuple[str, str], ExtractedTechnicalObject] = {}
    requirements: dict[str, RequirementItem] = {}
    designs: dict[str, DesignElement] = {}
    verifications: dict[str, VerificationItem] = {}
    links: dict[tuple[str, str, str], TraceLinkCandidate] = {}

    section_title_by_id = {
        section.section_id: section.title
        for section in bundle.section_tree.sections
    }
    for evidence in bundle.evidence_pool.evidences:
        text = evidence.excerpt or evidence.summary
        if not text:
            continue
        section_title = section_title_by_id.get(evidence.section_id, "")
        context_tags = _gnc_context_tags(f"{section_title}\n{text}")

        for param in _extract_parameters_from_text(text, evidence, context_tags):
            key = (param.normalized_name, param.source_evidence_id)
            parameters_by_key.setdefault(key, param)

        for obj in _extract_objects_from_text(text, evidence):
            key = (obj.name, obj.source_evidence_id)
            objects_by_key.setdefault(key, obj)

        ids = _extract_trace_ids(text)
        for req_id in ids["requirements"]:
            requirements.setdefault(
                req_id,
                RequirementItem(
                    requirement_id=req_id,
                    title=req_id,
                    text=_clip_text(text, 500),
                    source_section_id=evidence.section_id,
                    source_evidence_id=evidence.evidence_id,
                    block_ids=list(evidence.block_ids),
                    source_text=text,
                    confidence=0.55,
                ),
            )
        for design_id in ids["designs"]:
            designs.setdefault(
                design_id,
                DesignElement(
                    design_id=design_id,
                    name=design_id,
                    design_type="gnc_design",
                    normalized_name=design_id.lower(),
                    source_section_id=evidence.section_id,
                    source_evidence_id=evidence.evidence_id,
                    block_ids=list(evidence.block_ids),
                    source_text=text,
                    confidence=0.5,
                ),
            )
        for verification_id in ids["verifications"]:
            verifications.setdefault(
                verification_id,
                VerificationItem(
                    verification_id=verification_id,
                    title=verification_id,
                    method=_infer_verification_method(text),
                    status="completed" if any(k in text for k in ("结果", "通过", "满足")) else "planned",
                    pass_fail="pass" if any(k in text for k in ("通过", "满足", "合格")) else "partial",
                    source_section_id=evidence.section_id,
                    source_evidence_id=evidence.evidence_id,
                    block_ids=list(evidence.block_ids),
                    source_text=text,
                    confidence=0.5,
                ),
            )
        for source_id in ids["requirements"]:
            for target_id in ids["designs"]:
                links.setdefault(
                    (source_id, target_id, "requirement_to_design"),
                    _trace_candidate(source_id, target_id, "requirement_to_design", evidence, text),
                )
            for target_id in ids["verifications"]:
                links.setdefault(
                    (source_id, target_id, "requirement_to_verification"),
                    _trace_candidate(source_id, target_id, "requirement_to_verification", evidence, text),
                )
        for source_id in ids["designs"]:
            for target_id in ids["verifications"]:
                links.setdefault(
                    (source_id, target_id, "design_to_verification"),
                    _trace_candidate(source_id, target_id, "design_to_verification", evidence, text),
                )

    bundle.extracted_parameters = list(parameters_by_key.values())
    bundle.extracted_objects = list(objects_by_key.values())
    bundle.trace_link_candidates = list(links.values())
    bundle.requirements = list(requirements.values())
    bundle.design_elements = list(designs.values())
    bundle.verification_items = list(verifications.values())
    req_ids = set(requirements)
    linked_req_ids = {
        link.source_id
        for link in bundle.trace_link_candidates
        if link.link_type in {"requirement_to_design", "requirement_to_verification"}
    }
    bundle.traceability_matrix_summary = TraceabilityMatrixSummary(
        requirement_count=len(bundle.requirements),
        design_element_count=len(bundle.design_elements),
        verification_item_count=len(bundle.verification_items),
        candidate_link_count=len(bundle.trace_link_candidates),
        link_count=len(bundle.trace_link_candidates),
        requirement_decomposition_coverage=round(len(linked_req_ids) / max(len(req_ids), 1), 4) if req_ids else 0.0,
        uncovered_requirement_count=max(0, len(req_ids - linked_req_ids)),
        no_verification_requirement_ids=sorted(req_ids - linked_req_ids),
    )
