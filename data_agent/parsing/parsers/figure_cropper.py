"""Crop figure regions from PDF pages using MinerU bbox coordinates."""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def _bbox_to_rect(bbox: list[float], page_width: float, page_height: float):
    import fitz  # type: ignore

    if len(bbox) < 4:
        raise ValueError("bbox must have at least 4 values")
    x0, y0, x1, y1 = (float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3]))
    if x0 > x1:
        x0, x1 = x1, x0
    if y0 > y1:
        y0, y1 = y1, y0

    max_coord = max(x0, y0, x1, y1)
    if max_coord <= 1.5:
        scale_x = page_width
        scale_y = page_height
    elif max_coord <= 1000.0 + 1.0:
        scale_x = page_width / 1000.0
        scale_y = page_height / 1000.0
    else:
        scale_x = 1.0
        scale_y = 1.0

    rect = fitz.Rect(x0 * scale_x, y0 * scale_y, x1 * scale_x, y1 * scale_y)
    page_rect = fitz.Rect(0, 0, page_width, page_height)
    return rect & page_rect


def crop_figure_from_pdf(
    file_path: str,
    page_hint: int,
    bbox: list[float],
    output_path: str,
    *,
    zoom: float = 2.0,
) -> str | None:
    """Render a PDF page region to an image file. Returns output_path on success."""
    try:
        import fitz  # type: ignore
    except ImportError:
        logger.warning("[figure_cropper] PyMuPDF (fitz) not installed")
        return None

    if not bbox or page_hint is None or page_hint < 1:
        return None

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    doc = None
    try:
        doc = fitz.open(file_path)
        page_index = min(max(page_hint - 1, 0), len(doc) - 1)
        page = doc[page_index]
        rect = page.rect
        clip = _bbox_to_rect(bbox, float(rect.width), float(rect.height))
        if clip.is_empty or clip.width < 1 or clip.height < 1:
            return None
        matrix = fitz.Matrix(zoom, zoom)
        pixmap = page.get_pixmap(matrix=matrix, clip=clip, alpha=False)
        pixmap.save(str(output))
        return str(output)
    except Exception as exc:
        logger.warning("[figure_cropper] crop failed page=%s: %s", page_hint, exc)
        return None
    finally:
        if doc is not None:
            doc.close()


__all__ = ["crop_figure_from_pdf"]
