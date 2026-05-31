"""Static format damage detection for parsed document blocks."""

from __future__ import annotations

from data_agent.parsing.schemas import ParsedDocumentBlock
from data_agent.agents.format_guard.html_ast import damage_snippet as html_snippet
from data_agent.agents.format_guard.html_ast import scan_html_table_tags
from data_agent.agents.format_guard.latex_scanner import latex_damage_snippet as latex_snippet
from data_agent.agents.format_guard.latex_scanner import scan_latex_delimiters
from data_agent.agents.format_guard.schemas import BlockDamageReport, FormatDamageType

_DEFAULT_SKIP_TYPES = frozenset({"page_break"})


class FormatDetector:
    detector_version: str = "1.0"

    def detect(
        self,
        blocks: list[ParsedDocumentBlock],
        *,
        skip_block_types: set[str] | None = None,
    ) -> list[BlockDamageReport]:
        skip = skip_block_types if skip_block_types is not None else set(_DEFAULT_SKIP_TYPES)
        reports: list[BlockDamageReport] = []

        for block in blocks:
            if block.block_type in skip:
                continue
            damage_types = self.detect_block(block)
            if not damage_types:
                continue
            reports.append(
                BlockDamageReport(
                    block_id=block.block_id,
                    order_index=block.order_index,
                    damage_types=damage_types,
                    snippet=self._build_snippet(block, damage_types),
                    detector_version=self.detector_version,
                )
            )

        return reports

    def detect_block(self, block: ParsedDocumentBlock) -> list[FormatDamageType]:
        parts: list[str] = []
        if block.text:
            parts.append(block.text)
        if block.table_markdown:
            parts.append(block.table_markdown)
        if block.formula_latex:
            parts.append(block.formula_latex)
        if not parts:
            return []
        return self.detect_text("\n\n".join(parts))

    def detect_text(self, text: str) -> list[FormatDamageType]:
        """Scan a single text blob for HTML table and LaTeX delimiter issues."""
        if not text or not text.strip():
            return []

        seen: set[FormatDamageType] = set()
        ordered: list[FormatDamageType] = []

        for damage in scan_html_table_tags(text) + scan_latex_delimiters(text):
            if damage not in seen:
                seen.add(damage)
                ordered.append(damage)

        return ordered

    def _build_snippet(
        self,
        block: ParsedDocumentBlock,
        damage_types: list[FormatDamageType],
    ) -> str:
        parts: list[str] = []
        if block.text:
            parts.append(block.text)
        if block.table_markdown:
            parts.append(block.table_markdown)
        if block.formula_latex:
            parts.append(block.formula_latex)
        combined = "\n\n".join(parts)

        html_types = {
            FormatDamageType.UNCLOSED_HTML_TABLE,
            FormatDamageType.UNCLOSED_HTML_TR,
            FormatDamageType.UNCLOSED_HTML_TD,
        }
        latex_types = {
            FormatDamageType.ODD_INLINE_LATEX,
            FormatDamageType.ODD_BLOCK_LATEX,
        }

        snippets: list[str] = []
        if html_types.intersection(damage_types):
            snippets.append(html_snippet(combined))
        if latex_types.intersection(damage_types):
            snippets.append(latex_snippet(combined))
        return " | ".join(s for s in snippets if s)
