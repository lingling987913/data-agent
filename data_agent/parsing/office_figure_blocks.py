"""Materialize figure blocks from locally embedded Office images."""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
import uuid
from pathlib import Path

from data_agent.parsing.schemas import ParsedDocument, ParsedDocumentBlock

logger = logging.getLogger(__name__)

_DOCX_EXTENSION = ".docx"


def _is_figure_like_block(block: ParsedDocumentBlock) -> bool:
    block_type = (block.block_type or "").strip().lower()
    return block_type in {"figure", "image"}


def _existing_figure_keys(blocks: list[ParsedDocumentBlock]) -> set[tuple[str, str]]:
    keys: set[tuple[str, str]] = set()
    for block in blocks:
        if not _is_figure_like_block(block):
            continue
        keys.add(((block.image_ref or "").strip(), (block.caption or "").strip()))
        keys.add(((block.text or "").strip(), (block.caption or "").strip()))
    return keys


def _persist_image(
    source_path: str,
    *,
    figure_storage_dir: str | None,
    file_name: str,
    index: int,
) -> str:
    if not figure_storage_dir:
        return source_path
    storage = Path(figure_storage_dir)
    storage.mkdir(parents=True, exist_ok=True)
    suffix = Path(source_path).suffix or ".jpg"
    target = storage / f"{Path(file_name).stem}_embedded_{index}{suffix}"
    if Path(source_path).resolve() != target.resolve():
        shutil.copy2(source_path, target)
    return str(target)


def materialize_docx_embedded_figures(
    parsed_doc: ParsedDocument,
    file_path: str,
    file_name: str,
    *,
    figure_storage_dir: str | None = None,
) -> int:
    """Extract embedded DOCX images locally and append figure blocks."""
    ext = Path(file_name or file_path).suffix.lower()
    if ext != _DOCX_EXTENSION:
        return 0
    if parsed_doc.parse_status == "failed":
        return 0

    from data_agent.parsing.parsers.image_extractor import extract_embedded_images

    extract_dir = figure_storage_dir or os.path.join(
        os.path.dirname(file_path) or ".",
        ".embedded_figures",
    )
    os.makedirs(extract_dir, exist_ok=True)
    embedded_images = extract_embedded_images(file_path, file_name, extract_dir)
    if not embedded_images:
        return 0

    existing_keys = _existing_figure_keys(parsed_doc.blocks)
    added = 0
    for image in embedded_images:
        source_path = str(image.get("path") or "").strip()
        if not source_path or not os.path.isfile(source_path):
            continue
        index = int(image.get("index") or added)
        persisted = _persist_image(
            source_path,
            figure_storage_dir=figure_storage_dir,
            file_name=file_name,
            index=index,
        )
        caption = f"Figure {index + 1}"
        text = f"![{caption}]({persisted})"
        dedupe_key = (persisted, caption)
        if dedupe_key in existing_keys:
            continue
        parsed_doc.blocks.append(
            ParsedDocumentBlock(
                block_id=str(uuid.uuid4()),
                block_type="figure",
                text=text,
                caption=caption,
                image_ref=persisted,
                order_index=len(parsed_doc.blocks),
            )
        )
        existing_keys.add(dedupe_key)
        added += 1

    if added:
        parsed_doc.warnings.append(f"DOCX 本地抽图: 新增 {added} 个图片块。")
    return added


def should_materialize_docx_figures(
    file_path: str,
    file_name: str,
    parsed_doc: ParsedDocument,
    *,
    processing_mode: str | None,
    parser_type: str,
) -> bool:
    """True when local DOCX figure blocks should be created before VLM."""
    from data_agent.parsing.finalize import _image_desc_enabled_for_mode

    ext = Path(file_name or file_path or parsed_doc.file_name or "").suffix.lower()
    if ext != _DOCX_EXTENSION:
        return False
    if parsed_doc.parser_name in {"mineru-agent", "mineru-extract"}:
        return False
    if not _image_desc_enabled_for_mode(processing_mode, parser_type):
        return False
    if not file_path or not os.path.isfile(file_path):
        return False

    from data_agent.parsing.enhancers.llm_enhancer import _is_figure_block
    from data_agent.parsing.parsers.image_extractor import extract_embedded_images

    figure_count = sum(1 for block in parsed_doc.blocks if _is_figure_block(block))
    try:
        with tempfile.TemporaryDirectory(prefix="da_docx_probe_") as tmp_dir:
            embedded = extract_embedded_images(file_path, file_name, tmp_dir)
    except Exception as exc:
        logger.debug("[office_figure_blocks] embedded image probe failed: %s", exc)
        return figure_count == 0

    if not embedded:
        return False
    return figure_count < len(embedded)


__all__ = [
    "materialize_docx_embedded_figures",
    "should_materialize_docx_figures",
]
