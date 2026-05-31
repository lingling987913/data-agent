from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from data_agent.domain.material_roles import MaterialRole, TaskScenario, detect_scenario
from data_agent.review_plus.material_classifier_service import classify_material
from data_agent.review_plus.schemas import ReviewPlusMaterialRole


class ClassifiedMaterial(BaseModel):
    index: int
    file_name: str
    file_type: str = ""
    role: str = ReviewPlusMaterialRole.UNKNOWN.value
    confidence: float = 0.0
    reason: str = ""


class MetadataRoutingResult(BaseModel):
    """L0: fast metadata-only routing (<100ms target)."""

    file_count: int = 0
    format_families: list[str] = Field(default_factory=list)
    is_multi_document_package: bool = False
    scenario: str = TaskScenario.SINGLE_DOC_PARSE.value
    confidence: float = 0.0
    reason: str = ""


class TaskClassificationResult(BaseModel):
    """L1: task route + per-material roles."""

    route: str = "parse_only"
    metadata: MetadataRoutingResult = Field(default_factory=MetadataRoutingResult)
    material_roles: list[ClassifiedMaterial] = Field(default_factory=list)
    confidence: float = 0.0
    reason: str = ""


def _material_name(material: dict[str, Any]) -> str:
    file_path = str(material.get("file_path") or material.get("path") or "")
    return str(
        material.get("file_name")
        or material.get("filename")
        or material.get("name")
        or (Path(file_path).name if file_path else "")
        or f"material-{id(material)}"
    )


def _material_content(material: dict[str, Any]) -> str:
    value = material.get("content") or material.get("preview_content") or material.get("text") or ""
    return str(value)[:4000]


def _format_family(file_name: str) -> str:
    ext = Path(file_name).suffix.lower()
    if ext in (".xlsx", ".xls", ".csv"):
        return "spreadsheet"
    if ext in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff"):
        return "image"
    if ext == ".pdf":
        return "pdf"
    if ext in (".docx", ".doc", ".md", ".txt", ".html", ".htm", ".rtf"):
        return "document"
    if ext == ".tdms":
        return "test_data"
    return "other"


def _explicit_role(material: dict[str, Any], user_overrides: dict[str, Any] | None) -> str:
    role = material.get("role_hint") or material.get("role") or material.get("material_role")
    if role:
        value = getattr(role, "value", role)
        text = str(value)
        if text.startswith("ReviewPlusMaterialRole."):
            return text.rsplit(".", 1)[-1].lower()
        return text
    if not user_overrides:
        return ""
    role_by_name = user_overrides.get("roles") or user_overrides.get("material_roles") or {}
    if isinstance(role_by_name, dict):
        return str(role_by_name.get(_material_name(material)) or "")
    return ""


def classify_metadata(
    materials: list[dict[str, Any]],
    *,
    objective: str = "",
) -> MetadataRoutingResult:
    """L0 metadata routing from extensions, counts and objective hints."""
    if not materials:
        return MetadataRoutingResult(
            file_count=0,
            confidence=0.0,
            reason="no materials",
        )

    names = [_material_name(material) for material in materials]
    families = sorted({_format_family(name) for name in names})
    file_count = len(materials)
    scenario = detect_scenario([{"file_name": name} for name in names]).value

    corpus_hint = " ".join([objective, *names]).lower()
    if file_count >= 8:
        reason = "batch size suggests cross-package comparison"
        confidence = 0.9
    elif file_count >= 3 and scenario == TaskScenario.PACKAGE_REVIEW.value:
        reason = "multi-document package with review-rule spreadsheet"
        confidence = 0.85
    elif file_count > 1:
        reason = "multi-document upload"
        confidence = 0.75
    elif any(token in corpus_hint for token in ("gnc", "姿态", "轨控", "卫星")):
        reason = "single document with GNC intent"
        confidence = 0.7
    else:
        reason = "single document upload"
        confidence = 0.65

    return MetadataRoutingResult(
        file_count=file_count,
        format_families=families,
        is_multi_document_package=file_count > 1,
        scenario=scenario,
        confidence=round(confidence, 4),
        reason=reason,
    )


def _classify_material_roles(
    materials: list[dict[str, Any]],
    user_overrides: dict[str, Any] | None,
) -> list[ClassifiedMaterial]:
    classified: list[ClassifiedMaterial] = []
    for index, material in enumerate(materials, start=1):
        name = _material_name(material)
        explicit = _explicit_role(material, user_overrides)
        if explicit:
            role = explicit
            confidence = 1.0
            reason = "explicit role override"
        else:
            role_enum, confidence, reason = classify_material(
                name=name,
                content=_material_content(material),
                file_path=str(material.get("file_path") or material.get("path") or ""),
            )
            role = role_enum.value
        classified.append(
            ClassifiedMaterial(
                index=index,
                file_name=name,
                file_type=Path(name).suffix.lower().lstrip("."),
                role=role,
                confidence=round(float(confidence), 4),
                reason=reason,
            )
        )
    return classified


def _resolve_route(
    *,
    classified: list[ClassifiedMaterial],
    materials: list[dict[str, Any]],
    objective: str,
    metadata: MetadataRoutingResult,
) -> tuple[str, str]:
    role_set = {item.role for item in classified}
    corpus_hint = " ".join(
        [objective]
        + [item.file_name for item in classified]
        + [
            str(material.get("content_preview") or material.get("preview_content") or material.get("content") or "")[:300]
            for material in materials
        ]
    ).lower()
    # Review-Plus is a rule/checklist-driven review: it requires explicit review
    # criteria. A task book alone (without rules/checklist) is not a review package,
    # so it must not pre-empt a stronger GNC-review signal.
    has_review_criteria = bool(
        role_set
        & {
            ReviewPlusMaterialRole.REVIEW_RULE.value,
            ReviewPlusMaterialRole.CHECKLIST.value,
        }
    )
    has_subject = bool(
        role_set
        & {
            ReviewPlusMaterialRole.SUBJECT_REPORT.value,
            ReviewPlusMaterialRole.SUBJECT_DOCUMENT.value,
            ReviewPlusMaterialRole.SUPPORTING_ATTACHMENT.value,
        }
    )
    wants_gnc_strong = any(token in corpus_hint for token in ("gnc", "姿态", "轨控", "卫星"))
    wants_gnc_weak = any(token in corpus_hint for token in ("导航", "控制"))
    wants_gnc = wants_gnc_strong or (wants_gnc_weak and not has_review_criteria)
    wants_review = any(token in corpus_hint for token in ("review", "审查", "复核", "检查", "评审"))

    if metadata.scenario == TaskScenario.CROSS_PACKAGE_COMPARE.value and has_subject:
        return "review_plus", "cross-package compare with subject materials"
    if has_review_criteria and has_subject:
        return "review_plus", "materials match Review-Plus review-rule/checklist roles"
    if wants_gnc and (wants_review or has_subject):
        return "gnc_review", "objective indicates satellite/GNC review"
    if wants_review and has_subject:
        return "review_plus", "objective requests review and subject material exists"
    if metadata.scenario == TaskScenario.PACKAGE_REVIEW.value and has_subject:
        return "review_plus", "package review scenario with subject material"
    return "parse_only", "no review package pattern detected"


_REVIEW_PLUS_TO_MATERIAL_ROLE: dict[str, MaterialRole] = {
    ReviewPlusMaterialRole.REVIEW_RULE.value: MaterialRole.REVIEW_RULE,
    ReviewPlusMaterialRole.CHECKLIST.value: MaterialRole.CHECKLIST,
    ReviewPlusMaterialRole.TASK_BOOK.value: MaterialRole.TASK_BOOK,
    ReviewPlusMaterialRole.SUBJECT_REPORT.value: MaterialRole.SUBJECT_REPORT,
    ReviewPlusMaterialRole.SUBJECT_DOCUMENT.value: MaterialRole.MOTOR_SPEC,
    ReviewPlusMaterialRole.SUPPORTING_ATTACHMENT.value: MaterialRole.ENGINEERING_DRAWING,
}


def to_material_role(role: str, file_name: str = "") -> MaterialRole:
    """Map shared classifier role to Task API MaterialRole."""
    normalized = str(role or "").strip().lower()
    if normalized in _REVIEW_PLUS_TO_MATERIAL_ROLE:
        return _REVIEW_PLUS_TO_MATERIAL_ROLE[normalized]
    if normalized:
        try:
            return MaterialRole(normalized)
        except ValueError:
            pass

    name = file_name.lower()
    if "检查需求" in name and name.endswith(".xlsx"):
        return MaterialRole.REVIEW_RULE
    if "检查单" in name and name.endswith(".docx"):
        return MaterialRole.CHECKLIST
    if "任务书" in name and name.endswith(".docx"):
        return MaterialRole.TASK_BOOK
    if "可靠性" in name and "报告" in name:
        return MaterialRole.SUBJECT_REPORT
    if "验收报告" in name:
        return MaterialRole.ACCEPTANCE_REPORT
    if any(keyword in name for keyword in ("电机", "外框", "定子", "转子")):
        return MaterialRole.MOTOR_SPEC
    if any(keyword in name for keyword in ("同步器", "mapan", "码盘")):
        return MaterialRole.ENGINEERING_DRAWING
    if name.endswith(".tdms"):
        return MaterialRole.TEST_DATA
    return MaterialRole.UNKNOWN


def classify_batch(
    materials: list[dict[str, Any]],
    objective: str = "",
    user_overrides: dict[str, Any] | None = None,
) -> TaskClassificationResult:
    """Shared L0/L1 classifier for Super Agent, Review-Plus and Task API."""
    metadata = classify_metadata(materials, objective=objective)
    classified = _classify_material_roles(materials, user_overrides)
    route, reason = _resolve_route(
        classified=classified,
        materials=materials,
        objective=objective,
        metadata=metadata,
    )

    non_unknown = [item.confidence for item in classified if item.role != ReviewPlusMaterialRole.UNKNOWN.value]
    confidence = sum(non_unknown) / len(non_unknown) if non_unknown else metadata.confidence
    return TaskClassificationResult(
        route=route,
        metadata=metadata,
        material_roles=classified,
        confidence=round(confidence, 4),
        reason=reason,
    )


def normalize_planning_materials(metadata: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Normalize planning metadata materials for classify_batch."""
    if not metadata:
        return []
    materials = metadata.get("materials") or []
    normalized: list[dict[str, Any]] = []
    for item in materials:
        if not isinstance(item, dict):
            continue
        normalized.append(
            {
                "file_name": _material_name(item),
                "file_path": str(item.get("file_path") or item.get("path") or ""),
                "content": str(
                    item.get("content")
                    or item.get("content_preview")
                    or item.get("preview_content")
                    or ""
                ),
                "role_hint": item.get("role_hint") or item.get("role") or "",
            }
        )
    return normalized


def classify_for_planning(
    instruction: str,
    metadata: dict[str, Any] | None = None,
) -> tuple[TaskClassificationResult, dict[str, Any]]:
    """Run shared L0/L1 classification and enrich planning metadata."""
    meta = dict(metadata or {})
    materials = normalize_planning_materials(meta)
    user_overrides: dict[str, Any] = {}
    roles = meta.get("roles") or meta.get("material_roles")
    if isinstance(roles, dict):
        user_overrides["roles"] = roles

    classification = classify_batch(
        materials,
        objective=instruction,
        user_overrides=user_overrides or None,
    )
    enriched = {
        **meta,
        "task_route": classification.route,
        "task_classification": classification.model_dump(mode="json"),
    }
    if classification.material_roles:
        enriched["material_roles"] = {
            item.file_name: item.role for item in classification.material_roles
        }
    return classification, enriched


def resolve_parsing_tier(
    role: str,
    file_name: str,
    *,
    default_parser_type: str = "auto",
) -> dict[str, str | None]:
    """Map material role to L2 parsing tier (parser_type + processing_mode)."""
    normalized_role = str(role or ReviewPlusMaterialRole.UNKNOWN.value).strip().lower()
    ext = Path(file_name).suffix.lower()
    parser_default = (default_parser_type or "auto").strip().lower()

    if normalized_role in {
        ReviewPlusMaterialRole.REVIEW_RULE.value,
        ReviewPlusMaterialRole.CHECKLIST.value,
    } or ext in (".xlsx", ".xls", ".csv"):
        return {
            "tier": "lite",
            "parser_type": "local",
            "processing_mode": "HIGH_SPEED",
        }

    if normalized_role in {
        ReviewPlusMaterialRole.TASK_BOOK.value,
        ReviewPlusMaterialRole.SUBJECT_REPORT.value,
    }:
        from data_agent.parsing.material_parser_route import resolve_material_parser_route

        route = resolve_material_parser_route(
            file_name,
            parser_default if parser_default != "local" else "auto",
            "OPTIMAL",
        )
        return {
            "tier": "standard",
            "parser_type": route.parser_type,
            "processing_mode": "OPTIMAL",
        }

    if normalized_role in {
        ReviewPlusMaterialRole.SUBJECT_DOCUMENT.value,
        ReviewPlusMaterialRole.SUPPORTING_ATTACHMENT.value,
    }:
        from data_agent.parsing.material_parser_route import resolve_material_parser_route

        requested = parser_default if parser_default not in {"", "local"} else "auto"
        route = resolve_material_parser_route(file_name, requested, "HIGH_ACCURACY")
        return {
            "tier": "full",
            "parser_type": route.parser_type,
            "processing_mode": "HIGH_ACCURACY",
        }

    from data_agent.parsing.material_parser_route import resolve_material_parser_route

    route = resolve_material_parser_route(
        file_name,
        parser_default if parser_default else "auto",
        "OPTIMAL",
    )
    return {
        "tier": "standard",
        "parser_type": route.parser_type,
        "processing_mode": "OPTIMAL",
    }
