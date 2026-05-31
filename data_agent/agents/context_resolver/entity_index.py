"""Entity index for anaphora resolution context."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from data_agent.parsing.schemas import DocumentSection, DocumentSectionTree, ParsedDocumentBlock

EntityKind = Literal["section", "table", "formula", "figure"]


@dataclass
class EntityAnchor:
    entity_id: str
    label: str
    kind: EntityKind
    section_id: str | None = None
    block_id: str | None = None
    page_hint: int | None = None
    order_index: int = 0


@dataclass
class EntityIndex:
    anchors: list[EntityAnchor] = field(default_factory=list)
    _block_section: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_section_tree(
        cls,
        blocks: list[ParsedDocumentBlock],
        tree: DocumentSectionTree,
    ) -> EntityIndex:
        block_section = _map_blocks_to_sections(blocks, tree.sections)
        anchors: list[EntityAnchor] = []

        for section in tree.sections:
            label = _section_label(section)
            anchors.append(
                EntityAnchor(
                    entity_id=f"sec:{section.section_id}",
                    label=label,
                    kind="section",
                    section_id=section.section_id,
                    page_hint=section.page_hint_start,
                    order_index=section.start_block_index,
                )
            )

        for block in blocks:
            kind: EntityKind | None = None
            if block.block_type == "table":
                kind = "table"
            elif block.block_type == "formula":
                kind = "formula"
            elif block.block_type in ("figure", "figure_caption"):
                kind = "figure"
            elif block.block_type == "heading":
                kind = "section"

            if kind is None:
                continue

            section_id = block_section.get(block.block_id)
            section = next((s for s in tree.sections if s.section_id == section_id), None)
            label = (block.caption or block.text or "").strip()[:120]
            if section and not label:
                label = _section_label(section)
            if not label:
                label = f"{kind}@{block.order_index}"

            anchors.append(
                EntityAnchor(
                    entity_id=f"blk:{block.block_id}",
                    label=label,
                    kind=kind,
                    section_id=section_id,
                    block_id=block.block_id,
                    page_hint=block.page_hint,
                    order_index=block.order_index,
                )
            )

        anchors.sort(key=lambda a: a.order_index)
        return cls(anchors=anchors, _block_section=block_section)

    def candidates_for_block(
        self,
        block: ParsedDocumentBlock,
        *,
        window_sections: int = 3,
    ) -> list[EntityAnchor]:
        """Return nearby entity anchors for anaphora resolution."""
        idx = block.order_index
        nearby = [
            a
            for a in self.anchors
            if abs(a.order_index - idx) <= window_sections * 5
        ]
        if not nearby:
            return self.anchors[:10]
        return sorted(nearby, key=lambda a: abs(a.order_index - idx))[:15]

    def resolve_candidates(self, anaphora_span: str) -> list[str]:
        """Return label strings matching span keywords (rule-based pre-filter)."""
        keywords = ("表", "图", "公式", "章节", "方案", "算法", "上述", "前述")
        hits = [a.label for a in self.anchors if any(k in a.label for k in keywords)]
        if anaphora_span:
            hits = [a.label for a in self.anchors if anaphora_span in a.label] + hits
        seen: set[str] = set()
        out: list[str] = []
        for label in hits:
            if label not in seen:
                seen.add(label)
                out.append(label)
        return out[:10]


def _section_label(section: DocumentSection) -> str:
    number = (section.number or "").strip()
    title = (section.title or "").strip()
    if number and title:
        return f"{number} {title}"
    return title or number or section.section_id


def _map_blocks_to_sections(
    blocks: list[ParsedDocumentBlock],
    sections: list[DocumentSection],
) -> dict[str, str]:
    mapping: dict[str, str] = {}
    if not sections:
        return mapping
    sorted_sections = sorted(sections, key=lambda s: s.start_block_index)
    for block in blocks:
        for section in reversed(sorted_sections):
            if section.start_block_index <= block.order_index <= section.end_block_index:
                mapping[block.block_id] = section.section_id
                break
    return mapping
