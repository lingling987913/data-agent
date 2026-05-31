"""Material metadata normalization helpers for parsing entrypoints."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def material_items_from_metadata(metadata: dict[str, Any]) -> list[dict[str, Any]]:
    raw_items = (
        metadata.get("materials")
        or metadata.get("documents")
        or metadata.get("files")
        or []
    )
    items: list[dict[str, Any]] = []
    if isinstance(raw_items, list):
        for raw in raw_items:
            if isinstance(raw, dict):
                items.append(dict(raw))
    if not items:
        file_path = metadata.get("file_path") or metadata.get("path")
        file_name = metadata.get("file_name") or metadata.get("name")
        content = metadata.get("content")
        if file_path or content:
            items.append(
                {
                    "file_path": file_path,
                    "file_name": file_name,
                    "name": file_name,
                    "content": content,
                    "parser_type": metadata.get("parser_type"),
                    "processing_mode": metadata.get("processing_mode"),
                }
            )
    return items


def material_file_name(item: dict[str, Any], file_path: str = "") -> str:
    return str(
        item.get("file_name")
        or item.get("filename")
        or item.get("name")
        or (Path(file_path).name if file_path else "")
        or "material.txt"
    )
