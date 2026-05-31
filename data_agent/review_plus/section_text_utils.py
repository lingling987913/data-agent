"""Section-tree text helpers for Review-Plus mapping."""

from __future__ import annotations

from typing import Any

from data_agent.review_plus.schemas import ReviewPlusSectionMapping


def extract_flat_sections(section_tree: dict[str, Any]) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    raw_sections = section_tree.get("sections", [])

    def _walk(items: list[dict], depth: int = 0) -> None:
        for sec in items:
            text = sec.get("text", "") or ""
            sections.append({
                "section_id": sec.get("section_id", ""),
                "title": sec.get("title", ""),
                "level": sec.get("level", depth + 1),
                "text": text,
                "text_length": len(text),
            })
            children = sec.get("children", [])
            if children:
                _walk(children, depth + 1)

    _walk(raw_sections)
    return sections


def get_mapped_section_texts(
    mapping: ReviewPlusSectionMapping,
    section_tree: dict[str, Any],
    *,
    max_chars: int = 3000,
) -> str:
    """Return concatenated section text for a mapping against a section tree."""
    flat = extract_flat_sections(section_tree)
    id_to_text = {sec["section_id"]: sec["text"] for sec in flat}
    parts: list[str] = []
    total = 0
    for section_id in mapping.section_ids:
        text = id_to_text.get(section_id, "")
        if not text:
            continue
        parts.append(text)
        total += len(text)
        if total >= max_chars:
            break
    combined = "\n\n".join(parts)
    return combined[:max_chars]
