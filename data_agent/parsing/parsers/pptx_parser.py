"""PPTX format parser."""

from __future__ import annotations

import re
import uuid
import xml.etree.ElementTree as ET
import zipfile

from data_agent.parsing.schemas import ParsedDocument, ParsedDocumentBlock


def _pptx_slide_order(names: list[str]) -> list[str]:
    def slide_no(name: str) -> int:
        match = re.search(r"slide(\d+)\.xml$", name)
        return int(match.group(1)) if match else 10**9

    return sorted(
        [name for name in names if name.startswith("ppt/slides/slide") and name.endswith(".xml")],
        key=slide_no,
    )


def parse_pptx(file_path: str, parsed_doc: ParsedDocument) -> None:
    parsed_doc.parser_name = "pptx_zip_parser"
    parsed_doc.file_type = "presentation"
    ns = {
        "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
        "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    }
    try:
        blocks: list[ParsedDocumentBlock] = []
        with zipfile.ZipFile(file_path) as archive:
            names = archive.namelist()
            for slide_index, slide_name in enumerate(_pptx_slide_order(names), start=1):
                root = ET.fromstring(archive.read(slide_name))
                texts: list[str] = []
                for node in root.findall(".//a:t", ns):
                    if node.text and node.text.strip():
                        texts.append(node.text.strip())
                if texts:
                    blocks.append(
                        ParsedDocumentBlock(
                            block_id=str(uuid.uuid4()),
                            block_type="heading" if slide_index == 1 else "paragraph",
                            text=f"Slide {slide_index}: " + "\n".join(texts),
                            level=1 if slide_index == 1 else None,
                            page_hint=slide_index,
                            order_index=len(blocks),
                        )
                    )
                picture_count = len(root.findall(".//p:pic", ns))
                if picture_count:
                    blocks.append(
                        ParsedDocumentBlock(
                            block_id=str(uuid.uuid4()),
                            block_type="figure_caption",
                            text=f"Slide {slide_index}: {picture_count} picture element(s), low_confidence_visual_summary=true",
                            page_hint=slide_index,
                            order_index=len(blocks),
                        )
                    )
        parsed_doc.blocks = blocks
        if not blocks:
            parsed_doc.parse_status = "degraded"
            parsed_doc.warnings.append("PPTX parsed but no text/image elements were found.")
    except Exception as e:
        parsed_doc.parse_status = "failed"
        parsed_doc.warnings.append(f"PPTX parsing failed: {e}")
