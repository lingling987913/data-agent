"""Cross-document object registry for requirement closure review.

The registry keeps task-level indexes for extracted engineering objects so
later review rules can reason about a controlled document package instead of
scanning one material at a time.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from data_agent.review.p0_schemas import (
    DesignImplementationItem,
    MaterialItem,
    RequirementNode,
    VerificationClaim,
)


REQUIREMENT_DOCUMENT_ROLES = {"top_requirement", "decomposed_requirement"}
DESIGN_DOCUMENT_ROLES = {"design_solution", "interface_control"}
VERIFICATION_DOCUMENT_ROLES = {"simulation_report", "verification_plan", "verification_result"}
TRACEABILITY_DOCUMENT_ROLES = REQUIREMENT_DOCUMENT_ROLES | DESIGN_DOCUMENT_ROLES | VERIFICATION_DOCUMENT_ROLES

from data_agent.review.p0_shared_constants import extract_inline_artifact_ids


def build_cross_document_object_registry(
    materials: list[MaterialItem],
    requirements: list[RequirementNode],
    design_items: list[DesignImplementationItem],
    verification_claims: list[VerificationClaim],
) -> dict[str, Any]:
    """Build task-level object and reference indexes for formal materials."""
    material_index = {
        material.name: _material_payload(material)
        for material in materials
        if material.included_in_formal_review and material.document_role in TRACEABILITY_DOCUMENT_ROLES
    }
    allowed_source_files = set(material_index)

    requirement_entries = [
        _requirement_entry(item)
        for item in requirements
        if _object_in_allowed_material(item.source_file_name, allowed_source_files)
    ]
    design_entries = [
        _design_entry(item)
        for item in design_items
        if _object_in_allowed_material(item.source_file_name, allowed_source_files)
    ]
    verification_entries = [
        _verification_entry(item)
        for item in verification_claims
        if _object_in_allowed_material(item.source_file_name, allowed_source_files)
    ]

    objects_by_id: dict[str, dict[str, Any]] = {}
    for entry in [*requirement_entries, *design_entries, *verification_entries]:
        objects_by_id[entry["object_id"]] = entry

    references = _build_references(requirement_entries, design_entries, verification_entries, objects_by_id)

    return {
        "materials": material_index,
        "objects_by_id": objects_by_id,
        "requirements_by_id": {entry["object_id"]: entry for entry in requirement_entries},
        "design_items_by_id": {entry["object_id"]: entry for entry in design_entries},
        "verification_claims_by_id": {entry["object_id"]: entry for entry in verification_entries},
        "object_reference_index": _build_object_reference_index(objects_by_id.values()),
        "document_reference_index": _build_document_reference_index(references),
        "references": references,
        "summary": {
            "material_count": len(material_index),
            "requirement_count": len(requirement_entries),
            "design_item_count": len(design_entries),
            "verification_claim_count": len(verification_entries),
            "reference_count": len(references),
        },
    }


def _material_payload(material: MaterialItem) -> dict[str, Any]:
    return {
        "source_file": material.name,
        "document_role": material.document_role,
        "document_version": material.document_version,
        "baseline_id": material.baseline_id,
        "role_confirmed": material.role_confirmed,
        "included_in_formal_review": material.included_in_formal_review,
    }


def _requirement_entry(item: RequirementNode) -> dict[str, Any]:
    return _base_object_entry(
        object_id=item.requirement_id,
        object_type="requirement",
        source_file=item.source_file_name,
        section=item.source_section_id,
        evidence_ids=[item.source_evidence_id],
        quote=item.source_quote,
        references=item.parent_requirement_ids,
        metadata={
            "requirement_level": item.requirement_level,
            "metric_id": item.metric_id,
            "metric_name": item.metric_name,
            "target_value": item.target_value,
            "unit": item.unit,
        },
    )


def _design_entry(item: DesignImplementationItem) -> dict[str, Any]:
    return _base_object_entry(
        object_id=item.design_item_id,
        object_type="design_item",
        source_file=item.source_file_name,
        section=item.source_section_id,
        evidence_ids=[item.source_evidence_id],
        quote=item.source_quote,
        references=item.satisfies_requirement_ids,
        metadata={
            "item_type": item.item_type,
            "metric_id": item.metric_id,
            "observed_value": item.observed_value,
            "unit": item.unit,
        },
    )


def _verification_entry(item: VerificationClaim) -> dict[str, Any]:
    return _base_object_entry(
        object_id=item.verification_id,
        object_type="verification_claim",
        source_file=item.source_file_name,
        section=item.source_section_id,
        evidence_ids=[item.source_evidence_id],
        quote=item.source_quote,
        references=[*item.verifies_requirement_ids, *item.verifies_design_item_ids],
        metadata={
            "method": item.method,
            "status": item.status,
            "pass_fail": item.pass_fail,
            "metric_id": item.metric_id,
            "observed_value": item.observed_value,
            "unit": item.unit,
        },
    )


def _base_object_entry(
    *,
    object_id: str,
    object_type: str,
    source_file: str,
    section: str,
    evidence_ids: list[str],
    quote: str,
    references: list[str],
    metadata: dict[str, Any],
) -> dict[str, Any]:
    explicit_refs = list(dict.fromkeys([ref for ref in references if ref and ref != object_id]))
    inline_refs = [ref for ref in _extract_inline_references(quote) if ref != object_id]
    return {
        "object_id": object_id,
        "object_type": object_type,
        "source_file": source_file,
        "section": section,
        "evidence_ids": [item for item in evidence_ids if item],
        "references": list(dict.fromkeys([*explicit_refs, *inline_refs])),
        "source_quote": quote,
        "metadata": metadata,
    }


def _relation_type_for_reference(source_type: str, ref_id: str) -> str:
    """Infer relation type from source object role and target artifact id."""
    if ref_id.startswith("REQ-"):
        if source_type == "requirement":
            return "references_requirement"
        if source_type == "design_item":
            return "satisfies"
        if source_type == "verification_claim":
            return "verifies"
    if ref_id.startswith("DES-"):
        if source_type == "requirement":
            return "references_design"
        if source_type == "design_item":
            return "decomposes"
        if source_type == "verification_claim":
            return "verifies"
    if ref_id.startswith(("VER-", "SIM-", "TEST-")):
        if source_type in {"requirement", "design_item", "verification_claim"}:
            return "verifies"
    return ""


def _build_references(
    requirement_entries: list[dict[str, Any]],
    design_entries: list[dict[str, Any]],
    verification_entries: list[dict[str, Any]],
    objects_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    references: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    def add(source: dict[str, Any], target_id: str, relation_type: str) -> None:
        target = objects_by_id.get(target_id)
        if not target:
            return
        key = (source["object_id"], target_id, relation_type)
        if key in seen:
            return
        seen.add(key)
        references.append({
            "source_id": source["object_id"],
            "source_type": source["object_type"],
            "source_file": source["source_file"],
            "target_id": target_id,
            "target_type": target["object_type"],
            "target_file": target["source_file"],
            "relation_type": relation_type,
            "evidence_ids": list(dict.fromkeys([*source.get("evidence_ids", []), *target.get("evidence_ids", [])])),
            "source_section": source.get("section", ""),
            "target_section": target.get("section", ""),
        })

    for req in requirement_entries:
        for ref in req["references"]:
            relation_type = _relation_type_for_reference(req["object_type"], ref)
            if relation_type:
                add(req, ref, relation_type)
    for design in design_entries:
        for ref in design["references"]:
            relation_type = _relation_type_for_reference(design["object_type"], ref)
            if relation_type:
                add(design, ref, relation_type)
    for claim in verification_entries:
        for ref in claim["references"]:
            relation_type = _relation_type_for_reference(claim["object_type"], ref)
            if relation_type:
                add(claim, ref, relation_type)
    return references


def _build_object_reference_index(entries: Any) -> dict[str, list[dict[str, Any]]]:
    index: dict[str, list[dict[str, Any]]] = {}
    for entry in entries:
        index[entry["object_id"]] = [{
            "source_file": entry["source_file"],
            "section": entry["section"],
            "evidence_ids": entry["evidence_ids"],
        }]
    return index


def _build_document_reference_index(references: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    index: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for ref in references:
        key = f"{ref['source_file']} -> {ref['target_file']}"
        index[key].append(ref)
    return dict(index)


def _object_in_allowed_material(source_file_name: str, allowed_source_files: set[str]) -> bool:
    return not allowed_source_files or source_file_name in allowed_source_files


def _extract_inline_references(text: str) -> list[str]:
    return extract_inline_artifact_ids(text)
