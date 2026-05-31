"""从 DOCX/PDF 原始文件中提取嵌入图片。"""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

_EXT_ALIASES = {"jpeg": "jpg"}


def extract_embedded_images(file_path: str, file_name: str, output_dir: str) -> list[dict]:
    """
    从 DOCX/PDF 中提取嵌入图片，保存到 output_dir。

    返回 [{"index": 0, "path": "/tmp/xxx/img_0.jpg", "format": "jpg", "size": 12345}, ...]
    """
    os.makedirs(output_dir, exist_ok=True)
    ext = Path(file_name).suffix.lower()
    if ext == ".docx":
        return _extract_from_docx(file_path, output_dir)
    if ext == ".pdf":
        return _extract_from_pdf(file_path, output_dir)
    return []


def _normalize_ext(ext: str) -> str:
    ext = (ext or "jpg").lower().lstrip(".")
    return _EXT_ALIASES.get(ext, ext)


def _extract_from_docx(file_path: str, output_dir: str) -> list[dict]:
    """用 python-docx 提取 DOCX 中的嵌入图片。"""
    try:
        import docx
    except ImportError:
        logger.warning("[image_extractor] python-docx not installed")
        return []

    results: list[dict] = []
    try:
        doc = docx.Document(file_path)
        img_idx = 0
        for rel in doc.part.rels.values():
            if "image" not in rel.reltype:
                continue
            img_data = rel.target_part.blob
            raw_ext = rel.target_part.content_type.split("/")[-1]
            img_ext = _normalize_ext(raw_ext)
            img_name = f"img_{img_idx}.{img_ext}"
            img_path = os.path.join(output_dir, img_name)
            with open(img_path, "wb") as f:
                f.write(img_data)
            results.append({
                "index": img_idx,
                "path": img_path,
                "format": img_ext,
                "size": len(img_data),
            })
            img_idx += 1
    except Exception as exc:
        logger.warning("[image_extractor] DOCX extraction failed: %s", exc)
        return []
    return results


def _extract_from_pdf(file_path: str, output_dir: str) -> list[dict]:
    """从 PDF 提取嵌入图片（PyMuPDF/fitz）。"""
    try:
        import fitz  # PyMuPDF
    except ImportError:
        logger.warning("[image_extractor] PyMuPDF (fitz) not installed, skip PDF images")
        return []

    results: list[dict] = []
    seen_xrefs: set[int] = set()
    try:
        doc = fitz.open(file_path)
        for page_num in range(len(doc)):
            for img_index, img in enumerate(doc.get_page_images(page_num)):
                xref = img[0]
                if xref in seen_xrefs:
                    continue
                seen_xrefs.add(xref)
                base_image = doc.extract_image(xref)
                if not base_image:
                    continue
                img_bytes = base_image["image"]
                img_ext = _normalize_ext(base_image.get("ext", "jpg"))
                img_name = f"img_p{page_num}_{img_index}.{img_ext}"
                img_path = os.path.join(output_dir, img_name)
                with open(img_path, "wb") as f:
                    f.write(img_bytes)
                results.append({
                    "index": len(results),
                    "path": img_path,
                    "format": img_ext,
                    "size": len(img_bytes),
                })
        doc.close()
    except Exception as exc:
        logger.warning("[image_extractor] PDF extraction failed: %s", exc)
        return []
    return results
