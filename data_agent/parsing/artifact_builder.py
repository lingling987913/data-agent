"""Public builders for parsed-document artifacts.

This module is the boundary between low-level parsers and downstream review
workflows. Callers should depend on these functions and ``structuring/*`` helpers.
"""

from __future__ import annotations

from typing import Any

from data_agent.parsing.schemas import (
    DocumentEvidencePool,
    DocumentIR,
    DocumentSectionTree,
    ParsedDocument,
    ReviewDocumentBundle,
)
from data_agent.parsing.structuring.evidence_pool import build_document_evidence_pool
from data_agent.parsing.structuring.extraction import (
    attach_extracted_structured_objects as _attach_extracted_structured_objects,
)
from data_agent.parsing.structuring.section_tree import build_section_tree


def build_sections(
    parsed_doc: ParsedDocument,
    *,
    toc_entries: list[Any] | None = None,
    toc_block_indexes: set[int] | None = None,
) -> DocumentSectionTree:
    """Build a section tree from a parsed document."""
    return build_section_tree(
        parsed_doc,
        toc_entries=toc_entries,
        toc_block_indexes=toc_block_indexes,
    )


def prepare_document_ir(bundle: ReviewDocumentBundle, parsed_doc: ParsedDocument) -> DocumentIR:
    """Attach or return the bundle-local Document IR slice for one document."""
    from data_agent.parsing.document_ir_consumer import prepare_document_ir_for_parsed

    return prepare_document_ir_for_parsed(bundle.document_ir, parsed_doc)


def attach_document_ir(bundle: ReviewDocumentBundle) -> None:
    """Ensure every parsed document has Document IR attached to the bundle."""
    from data_agent.parsing.document_ir_consumer import (
        build_document_ir_for_parsed,
        document_ir_attached,
        merge_document_ir,
    )

    for document in bundle.parsed_documents:
        if document_ir_attached(bundle.document_ir, document.file_name):
            continue
        merge_document_ir(bundle.document_ir, build_document_ir_for_parsed(document))


def build_evidence_pool(
    section_tree: DocumentSectionTree,
    parsed_doc: ParsedDocument,
    *,
    document_ir: DocumentIR | None = None,
) -> DocumentEvidencePool:
    """Build the evidence pool for a parsed document and section tree."""
    return build_document_evidence_pool(
        section_tree,
        parsed_doc,
        document_ir=document_ir,
    )


def attach_extracted_structured_objects(bundle: ReviewDocumentBundle) -> None:
    """Attach extracted parameters/objects/trace links to a review bundle."""
    _attach_extracted_structured_objects(bundle)


def is_parse_artifact_complete(
    parse_artifact: dict | None,
    *,
    require_document_ir: bool = True,
) -> bool:
    """Return whether Step-3 parse output is complete enough to run structuring without re-parse."""
    if not parse_artifact:
        return False
    file_results = parse_artifact.get("file_results") or []
    if not file_results:
        return False
    if any(item.get("parse_status") == "failed" for item in file_results):
        return False
    parsed_documents = parse_artifact.get("parsed_documents") or []
    has_documents = any(
        isinstance(item, dict) and item.get("document")
        for item in parsed_documents
    )
    if not has_documents:
        documents = parse_artifact.get("documents") or []
        has_documents = any(
            isinstance(item, dict) and item.get("document")
            for item in documents
        )
    if not has_documents:
        return False
    if not require_document_ir:
        return True
    document_ir = parse_artifact.get("document_ir") or {}
    if isinstance(document_ir, dict):
        return bool(
            document_ir.get("layout_blocks")
            or document_ir.get("table_elements")
            or document_ir.get("visual_elements")
            or document_ir.get("pages")
        )
    return bool(document_ir)


def is_structure_artifact_complete(
    section_tree: dict | DocumentSectionTree | None,
    evidence_pool: dict | DocumentEvidencePool | None,
    *,
    document_ir: dict | DocumentIR | None = None,
    parse_artifact: dict | None = None,
) -> bool:
    """Return whether reusable structure artifacts are complete enough to skip rebuild."""
    if isinstance(section_tree, DocumentSectionTree):
        sections = section_tree.sections
    else:
        sections = (section_tree or {}).get("sections") or []
    if isinstance(evidence_pool, DocumentEvidencePool):
        evidences = evidence_pool.evidences
    else:
        evidences = (evidence_pool or {}).get("evidences") or []
    if not (sections and evidences):
        return False

    if document_ir:
        if isinstance(document_ir, DocumentIR):
            has_ir = bool(
                document_ir.layout_blocks
                or document_ir.table_elements
                or document_ir.visual_elements
                or document_ir.pages
            )
        else:
            has_ir = bool(
                (document_ir or {}).get("layout_blocks")
                or (document_ir or {}).get("table_elements")
                or (document_ir or {}).get("visual_elements")
                or (document_ir or {}).get("pages")
            )
        if not has_ir:
            return False

    if parse_artifact:
        artifact_tree = parse_artifact.get("section_tree") or {}
        artifact_pool = parse_artifact.get("evidence_pool") or {}
        artifact_ir = parse_artifact.get("document_ir") or {}
        artifact_sections = artifact_tree.get("sections") if isinstance(artifact_tree, dict) else []
        artifact_evidences = artifact_pool.get("evidences") if isinstance(artifact_pool, dict) else []
        has_embedded_structure = "section_tree" in parse_artifact or "evidence_pool" in parse_artifact
        if has_embedded_structure and not (artifact_sections and artifact_evidences):
            return False
        if artifact_ir and not (
            artifact_ir.get("layout_blocks")
            or artifact_ir.get("table_elements")
            or artifact_ir.get("visual_elements")
            or artifact_ir.get("pages")
        ):
            return False

    return True
