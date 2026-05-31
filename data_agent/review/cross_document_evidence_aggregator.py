"""Cross-document evidence chain aggregation for traceability review items."""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Any

from data_agent.review.trace_link_utils import active_trace_links

from data_agent.review.p0_schemas import (
    CrossDocumentReviewItem,
    DesignImplementationItem,
    RequirementNode,
    RequirementTraceLink,
    VerificationClaim,
)


def attach_cross_document_evidence_chains(
    review_items: list[CrossDocumentReviewItem],
    requirements: list[RequirementNode],
    design_items: list[DesignImplementationItem],
    verification_claims: list[VerificationClaim],
    links: list[RequirementTraceLink],
    object_registry: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    """Attach compact evidence chains to review items and return them by item id."""
    object_index = _object_index(requirements, design_items, verification_claims, object_registry)
    graph = _trace_graph(active_trace_links(links))
    chains_by_item: dict[str, list[dict[str, Any]]] = {}

    for item in review_items:
        seed_ids = [artifact_id for artifact_id in [*item.source_artifact_ids, *item.target_artifact_ids] if artifact_id]
        chain_ids = _expand_chain_ids(seed_ids, graph, object_index)
        chain = [_evidence_entry(object_index[artifact_id]) for artifact_id in chain_ids if artifact_id in object_index]
        if not chain and item.evidence_ids:
            chain = _fallback_evidence_chain(item)
        item.evidence_chain = chain
        item.evidence_chain_summary = _chain_summary(chain)
        chains_by_item[item.review_item_id] = chain
    return chains_by_item


def _object_index(
    requirements: list[RequirementNode],
    design_items: list[DesignImplementationItem],
    verification_claims: list[VerificationClaim],
    object_registry: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for req in requirements:
        index[req.requirement_id] = {
            "object_id": req.requirement_id,
            "object_type": "requirement",
            "source_file": req.source_file_name,
            "section": req.source_section_id,
            "evidence_ids": [req.source_evidence_id] if req.source_evidence_id else [],
            "summary": req.source_quote or req.text or req.title,
            "level": req.requirement_level,
        }
    for item in design_items:
        index[item.design_item_id] = {
            "object_id": item.design_item_id,
            "object_type": "design_item",
            "source_file": item.source_file_name,
            "section": item.source_section_id,
            "evidence_ids": [item.source_evidence_id] if item.source_evidence_id else [],
            "summary": item.source_quote or item.text or item.title,
        }
    for claim in verification_claims:
        index[claim.verification_id] = {
            "object_id": claim.verification_id,
            "object_type": "verification_claim",
            "source_file": claim.source_file_name,
            "section": claim.source_section_id,
            "evidence_ids": [claim.source_evidence_id] if claim.source_evidence_id else [],
            "summary": claim.source_quote or claim.title,
        }
    for object_id, entry in (object_registry.get("objects_by_id") or {}).items():
        if object_id in index:
            continue
        index[object_id] = {
            "object_id": object_id,
            "object_type": entry.get("object_type", ""),
            "source_file": entry.get("source_file", ""),
            "section": entry.get("section", ""),
            "evidence_ids": entry.get("evidence_ids", []),
            "summary": entry.get("source_quote", ""),
        }
    return index


def _trace_graph(links: list[RequirementTraceLink]) -> dict[str, list[str]]:
    graph: dict[str, list[str]] = defaultdict(list)
    for link in links:
        if not link.source_id or not link.target_id:
            continue
        graph[link.source_id].append(link.target_id)
        graph[link.target_id].append(link.source_id)
    return graph


def _expand_chain_ids(seed_ids: list[str], graph: dict[str, list[str]], object_index: dict[str, dict[str, Any]]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    queue: deque[tuple[str, int]] = deque((seed_id, 0) for seed_id in seed_ids if seed_id in object_index)
    while queue:
        artifact_id, depth = queue.popleft()
        if artifact_id in seen or depth > 3:
            continue
        seen.add(artifact_id)
        ordered.append(artifact_id)
        for next_id in graph.get(artifact_id, []):
            if next_id not in seen and next_id in object_index:
                queue.append((next_id, depth + 1))
    return sorted(ordered, key=lambda artifact_id: (_chain_rank(object_index[artifact_id]), ordered.index(artifact_id)))


def _chain_rank(entry: dict[str, Any]) -> int:
    if entry.get("object_type") == "requirement" and entry.get("level") == "top":
        return 0
    if entry.get("object_type") == "requirement":
        return 1
    if entry.get("object_type") == "design_item":
        return 2
    if entry.get("object_type") == "verification_claim":
        return 3
    return 9


def _evidence_entry(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "artifact_id": entry.get("object_id", ""),
        "artifact_type": entry.get("object_type", ""),
        "source_file": entry.get("source_file", ""),
        "section": entry.get("section", ""),
        "evidence_ids": entry.get("evidence_ids", []),
        "summary": _compact(entry.get("summary", "")),
    }


def _fallback_evidence_chain(item: CrossDocumentReviewItem) -> list[dict[str, Any]]:
    return [{
        "artifact_id": artifact_id,
        "artifact_type": "evidence",
        "source_file": "",
        "section": "",
        "evidence_ids": [artifact_id],
        "summary": _compact(item.source_quote),
    } for artifact_id in item.evidence_ids]


def _chain_summary(chain: list[dict[str, Any]]) -> str:
    labels = [
        f"{entry.get('source_file') or entry.get('artifact_id')} {entry.get('section') or ''}".strip()
        for entry in chain
        if entry.get("source_file") or entry.get("artifact_id")
    ]
    return " -> ".join(labels)


def _compact(text: str, limit: int = 160) -> str:
    value = " ".join((text or "").split())
    if len(value) <= limit:
        return value
    return f"{value[:limit - 3]}..."
