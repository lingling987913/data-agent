from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from data_agent.parsing.schemas import ParsedDocument, ReviewDocumentBundle
from data_agent.parsing.parse_artifacts import (
    ParseArtifact,
    ParseOnlyArtifact,
    StructureArtifact,
    build_parse_only_artifact_from_parsed,
    parse_materials_to_batch,
    build_structure_artifact as _build_structure_artifact,
    build_structured_bundle_from_documents as _build_structured_bundle_from_documents,
    merge_parse_and_structure as _merge_parse_and_structure,
    per_file_structure_slices as _per_file_structure_slices,
)
from data_agent.parsing.materials import material_file_name, material_items_from_metadata

logger = logging.getLogger(__name__)

def _material_role_from_item(item: dict[str, Any], material_roles: dict[str, Any] | None = None) -> str:
    file_name = material_file_name(item)
    role = item.get("role_hint") or item.get("role") or item.get("material_role") or ""
    if role:
        return str(getattr(role, "value", role))
    if isinstance(material_roles, dict):
        value = material_roles.get(file_name) or material_roles.get(item.get("name") or "")
        if value:
            return str(getattr(value, "value", value))
    return ""


def parse_material_items(
    materials: list[dict[str, Any]],
    *,
    default_parser_type: str = "",
    default_processing_mode: str | None = None,
    material_roles: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compatibility wrapper for the parsing-layer batch parser."""
    parse_inputs: list[dict[str, Any]] = []
    for raw in materials:
        item = dict(raw)
        role_value = _material_role_from_item(item, material_roles)
        if not item.get("parser_type") and role_value:
            from data_agent.services.task_classifier import resolve_parsing_tier

            file_name = material_file_name(item, str(item.get("file_path") or item.get("path") or ""))
            tier = resolve_parsing_tier(
                role_value,
                file_name,
                default_parser_type=default_parser_type or "auto",
            )
            item["parser_type"] = str(tier.get("parser_type") or default_parser_type or "auto")
            item["processing_mode"] = item.get("processing_mode") or tier.get("processing_mode")
        parse_inputs.append(item)

    return parse_materials_to_batch(
        parse_inputs,
        default_parser_type=default_parser_type,
        default_processing_mode=default_processing_mode,
    )


def build_parse_only_artifact(
    materials: list[dict[str, Any]] | None = None,
    *,
    parsed: dict[str, Any] | None = None,
    default_parser_type: str = "",
    default_processing_mode: str | None = None,
    material_roles: dict[str, Any] | None = None,
) -> ParseOnlyArtifact:
    """Step 3: parse materials and attach Document IR without structuring."""
    if parsed is None:
        if not materials:
            raise ValueError("materials required when parsed is not provided")
        parsed = parse_material_items(
            materials,
            default_parser_type=default_parser_type,
            default_processing_mode=default_processing_mode,
            material_roles=material_roles,
        )
    return build_parse_only_artifact_from_parsed(parsed)


def build_structure_artifact(
    parse_artifact: ParseOnlyArtifact | dict[str, Any],
    *,
    documents: list[ParsedDocument] | None = None,
) -> StructureArtifact:
    return _build_structure_artifact(parse_artifact, documents=documents)



def merge_parse_and_structure(
    parse_only: ParseOnlyArtifact | dict[str, Any],
    structure: StructureArtifact | dict[str, Any],
) -> ParseArtifact:
    return _merge_parse_and_structure(parse_only, structure)



def per_file_structure_slices(
    artifact: ParseArtifact | dict[str, Any],
    file_name: str,
) -> dict[str, Any]:
    return _per_file_structure_slices(artifact, file_name)



def build_parse_artifact(
    materials: list[dict[str, Any]] | None = None,
    *,
    parsed: dict[str, Any] | None = None,
    default_parser_type: str = "",
    default_processing_mode: str | None = None,
    material_roles: dict[str, Any] | None = None,
    include_structure: bool = True,
) -> ParseArtifact:
    """Build parse artifact; structuring is optional and runs in a separate step when disabled."""
    parse_only = build_parse_only_artifact(
        materials,
        parsed=parsed,
        default_parser_type=default_parser_type,
        default_processing_mode=default_processing_mode,
        material_roles=material_roles,
    )
    if not include_structure:
        return merge_parse_and_structure(
            parse_only,
            StructureArtifact(parse_artifact_id=parse_only.artifact_id),
        )
    structure = build_structure_artifact(parse_only)
    return merge_parse_and_structure(parse_only, structure)


def build_structured_bundle_from_documents(documents: list[ParsedDocument]) -> ReviewDocumentBundle:
    return _build_structured_bundle_from_documents(documents)
