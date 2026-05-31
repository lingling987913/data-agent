"""Pre-parse orientation normalization for scanned landscape documents."""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

ORIENTATION_ALGO_VERSION = "v2"
_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".jp2", ".webp", ".gif", ".bmp"}
_PDF_DEPENDENCY_WARNING = "PDF 方向预处理未执行：缺少 PyMuPDF/pymupdf，横向扫描页可能影响 OCR 表格识别。"
_IMAGE_DEPENDENCY_WARNING = "图片方向预处理未执行：缺少 Pillow，横向图片可能影响 OCR 识别。"
_LANDSCAPE_CANDIDATES = (90, 270)
_PORTRAIT_FLIP_CANDIDATES = (0, 180)


@dataclass
class OrientationNormalizedFile:
    """A temporary normalized file plus cleanup ownership."""

    file_path: str
    changed: bool = False
    warnings: list[str] = field(default_factory=list)
    _temp_dir: tempfile.TemporaryDirectory[str] | None = None

    def cleanup(self) -> None:
        if self._temp_dir is not None:
            self._temp_dir.cleanup()
            self._temp_dir = None


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _enabled() -> bool:
    return _env_bool("PARSING_NORMALIZE_LANDSCAPE_SCANS", True)


def _orientation_mode() -> str:
    return (os.getenv("PARSING_ORIENTATION_MODE", "auto") or "auto").strip().lower()


def _landscape_ratio() -> float:
    return max(1.0, _env_float("PARSING_LANDSCAPE_RATIO", 1.05))


def _rotation_degrees() -> int:
    raw = _env_int("PARSING_LANDSCAPE_ROTATION_DEGREES", 90)
    if raw not in {90, 180, 270, -90, -180, -270}:
        return 90
    return raw % 360


def _score_margin_ratio() -> float:
    return max(0.0, _env_float("PARSING_ORIENTATION_SCORE_MARGIN", 0.05))


def _scan_text_threshold() -> int:
    return max(0, _env_int("PARSING_SCANNED_PAGE_TEXT_THRESHOLD", 20))


def _render_max_side() -> int:
    return max(128, _env_int("PARSING_ORIENTATION_RENDER_MAX_SIDE", 800))


def normalized_display_path_for(source_path: Path | str) -> Path:
    path = Path(source_path)
    return path.with_name(f"{path.stem}.normalized.{ORIENTATION_ALGO_VERSION}{path.suffix}")


def legacy_normalized_display_paths(source_path: Path | str) -> list[Path]:
    path = Path(source_path)
    return [path.with_name(f"{path.stem}.normalized{path.suffix}")]


def display_copy_needs_regeneration(source_path: Path | str, normalized_path: Path | str) -> bool:
    source = Path(source_path)
    normalized = Path(normalized_path)
    if not normalized.exists() or not normalized.is_file():
        return True
    if not source.exists():
        return False
    return source.stat().st_mtime > normalized.stat().st_mtime


def _temp_output(source: str) -> tuple[tempfile.TemporaryDirectory[str], Path]:
    tmp = tempfile.TemporaryDirectory(prefix="data-agent-orient-")
    target = Path(tmp.name) / Path(source).name
    return tmp, target


def _is_landscape(width: float, height: float) -> bool:
    return width > height * _landscape_ratio()


def _page_text_length(page: Any) -> int:
    try:
        text = page.get_text("text")
    except Exception:
        return 0
    return len(str(text or "").strip())


def _top_heaviness_ratio(gray_image: Any) -> float:
    width, height = gray_image.size
    pixels = gray_image.load()
    top_weight = 0.0
    bottom_weight = 0.0
    half = height // 2
    for y in range(height):
        row_weight = sum(255 - int(pixels[x, y]) for x in range(width))
        if y < half:
            top_weight += row_weight
        else:
            bottom_weight += row_weight
    total = top_weight + bottom_weight
    if total <= 0:
        return 0.5
    return top_weight / total


def _score_reading_orientation(gray_image: Any) -> float:
    """Heuristic readability score — higher when text lines align horizontally."""
    width, height = gray_image.size
    if width <= 1 or height <= 1:
        return 0.0

    pixels = gray_image.load()
    row_sums = [sum(pixels[x, y] for x in range(width)) for y in range(height)]
    row_mean = sum(row_sums) / len(row_sums)
    row_variance = sum((value - row_mean) ** 2 for value in row_sums) / len(row_sums)

    horizontal_edge = 0.0
    vertical_edge = 0.0
    for y in range(height):
        for x in range(width - 1):
            horizontal_edge += abs(int(pixels[x, y]) - int(pixels[x + 1, y]))
    for y in range(height - 1):
        for x in range(width):
            vertical_edge += abs(int(pixels[x, y]) - int(pixels[x, y + 1]))

    edge_ratio = horizontal_edge / max(vertical_edge, 1.0)
    top_heaviness = _top_heaviness_ratio(gray_image)
    ink_total = sum(255 - int(pixels[x, y]) for y in range(height) for x in range(width))
    top_bonus = max(0.0, top_heaviness - 0.5) * ink_total * 2.0
    return row_variance + edge_ratio * 1000.0 + top_bonus


def _choose_best_rotation(gray_image: Any, candidates: tuple[int, ...]) -> tuple[int, float, float]:
    best_angle = candidates[0]
    best_score = float("-inf")
    second_score = float("-inf")
    for angle in candidates:
        rotated = gray_image.rotate(angle, expand=True)
        score = _score_reading_orientation(rotated)
        if score > best_score:
            second_score = best_score
            best_score = score
            best_angle = angle
        elif score > second_score:
            second_score = score
    return best_angle, best_score, second_score


def _pick_rotation_with_margin(
    gray_image: Any,
    candidates: tuple[int, ...],
    *,
    fallback: int,
) -> tuple[int, list[str]]:
    warnings: list[str] = []
    if _orientation_mode() == "fixed":
        return fallback, warnings

    best_angle, best_score, second_score = _choose_best_rotation(gray_image, candidates)
    if best_score <= 0:
        warnings.append("方向评分不可用，已回退为固定旋转角度。")
        return fallback, warnings

    if second_score > float("-inf") and second_score > 0:
        margin = (best_score - second_score) / max(best_score, 1.0)
        if margin < _score_margin_ratio():
            warnings.append(
                f"方向评分接近（{best_angle}° vs 其他候选），已选用得分最高方向 {best_angle}°。"
            )

    return best_angle, warnings


def _consensus_rotation(candidates: list[int]) -> int:
    if not candidates:
        return _rotation_degrees()
    return max(set(candidates), key=candidates.count)


def _propose_landscape_correction(page: Any) -> tuple[int, list[str]]:
    if _orientation_mode() == "fixed":
        return _rotation_degrees(), []
    gray = _render_page_gray(page)
    return _pick_rotation_with_margin(
        gray,
        _LANDSCAPE_CANDIDATES,
        fallback=_rotation_degrees(),
    )


def _render_page_gray(page: Any, *, max_side: int | None = None) -> Any:
    import fitz  # type: ignore
    from PIL import Image  # type: ignore

    limit = max_side or _render_max_side()
    rect = page.rect
    width = float(getattr(rect, "width", 0) or 0)
    height = float(getattr(rect, "height", 0) or 0)
    if width <= 0 or height <= 0:
        raise ValueError("invalid page dimensions")

    scale = min(1.0, limit / max(width, height))
    matrix = fitz.Matrix(scale, scale)
    pixmap = page.get_pixmap(matrix=matrix, alpha=False)
    mode = "RGB" if pixmap.n >= 3 else "L"
    image = Image.frombytes(mode, (pixmap.width, pixmap.height), pixmap.samples)
    return image.convert("L")


def _choose_portrait_flip(page: Any) -> tuple[int, list[str]]:
    gray = _render_page_gray(page)
    best_angle, best_score, second_score = _choose_best_rotation(gray, _PORTRAIT_FLIP_CANDIDATES)
    if _orientation_mode() == "fixed" or best_score <= 0:
        return 0, []
    if second_score > float("-inf") and second_score > 0:
        margin = (best_score - second_score) / max(best_score, 1.0)
        if margin < _score_margin_ratio():
            return 0, []
    return best_angle if best_angle != 0 else 0, []


def _normalize_pdf_orientation(file_path: str, file_name: str) -> OrientationNormalizedFile:
    try:
        import fitz  # type: ignore
    except Exception:
        logger.debug("[orientation] PyMuPDF unavailable; skip PDF orientation normalization")
        return OrientationNormalizedFile(file_path=file_path, warnings=[_PDF_DEPENDENCY_WARNING])

    doc = None
    tmp: tempfile.TemporaryDirectory[str] | None = None
    try:
        doc = fitz.open(file_path)
        rotated_pages: list[tuple[int, int]] = []
        extra_warnings: list[str] = []
        landscape_jobs: list[tuple[int, Any, int, int, list[str]]] = []
        portrait_jobs: list[tuple[int, Any, int, int, list[str]]] = []

        for index, page in enumerate(doc, start=1):
            rect = page.rect
            width = float(getattr(rect, "width", 0) or 0)
            height = float(getattr(rect, "height", 0) or 0)
            if not width or not height:
                continue
            if _page_text_length(page) > _scan_text_threshold():
                continue

            current_rotation = int(getattr(page, "rotation", 0) or 0)
            if _is_landscape(width, height):
                delta, page_warnings = _propose_landscape_correction(page)
                landscape_jobs.append((index, page, current_rotation, delta, page_warnings))
            else:
                delta, page_warnings = _choose_portrait_flip(page)
                if delta == 0:
                    extra_warnings.extend(page_warnings)
                    continue
                portrait_jobs.append((index, page, current_rotation, delta, page_warnings))

        if len(landscape_jobs) >= 2 and _orientation_mode() != "fixed":
            consensus = _consensus_rotation([job[3] for job in landscape_jobs])
            proposed = {job[3] for job in landscape_jobs}
            if len(proposed) > 1:
                extra_warnings.append(
                    f"已用文档多数方向 {consensus}° 统一校正 {len(landscape_jobs)} 页横向扫描页。"
                )
            landscape_jobs = [
                (index, page, current_rotation, consensus, page_warnings)
                for index, page, current_rotation, _, page_warnings in landscape_jobs
            ]

        for index, page, current_rotation, delta, page_warnings in [*landscape_jobs, *portrait_jobs]:
            extra_warnings.extend(page_warnings)
            page.set_rotation((current_rotation + delta) % 360)
            rotated_pages.append((index, delta))

        if not rotated_pages:
            return OrientationNormalizedFile(file_path=file_path, warnings=extra_warnings)

        tmp, target = _temp_output(file_path)
        doc.save(str(target), garbage=4, deflate=True)
        angle_summary = ", ".join(f"{page}:{delta}°" for page, delta in rotated_pages[:5])
        if len(rotated_pages) > 5:
            angle_summary += "…"
        warning = (
            f"解析前已将 {len(rotated_pages)} 页扫描 PDF 按内容方向校正为纵向"
            f"（逐页 {angle_summary}）。"
        )
        unique_warnings: list[str] = []
        seen_warnings: set[str] = set()
        for item in [warning, *extra_warnings]:
            if item not in seen_warnings:
                seen_warnings.add(item)
                unique_warnings.append(item)
        return OrientationNormalizedFile(
            file_path=str(target),
            changed=True,
            warnings=unique_warnings,
            _temp_dir=tmp,
        )
    except Exception as exc:
        logger.warning("[orientation] failed to normalize PDF orientation for %s: %s", file_name, exc)
        if tmp is not None:
            tmp.cleanup()
        return OrientationNormalizedFile(file_path=file_path)
    finally:
        if doc is not None:
            try:
                doc.close()
            except Exception:
                pass


def _normalize_image_orientation(file_path: str, file_name: str) -> OrientationNormalizedFile:
    try:
        from PIL import Image, ImageOps  # type: ignore
    except Exception:
        logger.debug("[orientation] Pillow unavailable; skip image orientation normalization")
        return OrientationNormalizedFile(file_path=file_path, warnings=[_IMAGE_DEPENDENCY_WARNING])

    tmp: tempfile.TemporaryDirectory[str] | None = None
    try:
        with Image.open(file_path) as image:
            image = ImageOps.exif_transpose(image)
            width, height = image.size
            gray = image.convert("L")
            extra_warnings: list[str] = []

            if _is_landscape(float(width), float(height)):
                delta, extra_warnings = _pick_rotation_with_margin(
                    gray,
                    _LANDSCAPE_CANDIDATES,
                    fallback=_rotation_degrees(),
                )
            else:
                delta, extra_warnings = _choose_portrait_flip_from_gray(gray)
                if delta == 0:
                    return OrientationNormalizedFile(file_path=file_path, warnings=extra_warnings)

            tmp, target = _temp_output(file_path)
            normalized = image.rotate(delta, expand=True)
            image_format = image.format
            if image_format:
                normalized.save(target, format=image_format)
            else:
                normalized.save(target)

        return OrientationNormalizedFile(
            file_path=str(target),
            changed=True,
            warnings=[f"解析前已将图片 {file_name} 按内容方向校正为纵向（{delta}°）。", *extra_warnings],
            _temp_dir=tmp,
        )
    except Exception as exc:
        logger.warning("[orientation] failed to normalize image orientation for %s: %s", file_name, exc)
        if tmp is not None:
            tmp.cleanup()
        return OrientationNormalizedFile(file_path=file_path)


def _choose_portrait_flip_from_gray(gray_image: Any) -> tuple[int, list[str]]:
    if _orientation_mode() == "fixed":
        return 0, []
    best_angle, best_score, second_score = _choose_best_rotation(gray_image, _PORTRAIT_FLIP_CANDIDATES)
    if best_score <= 0 or best_angle == 0:
        return 0, []
    if second_score > float("-inf") and second_score > 0:
        margin = (best_score - second_score) / max(best_score, 1.0)
        if margin < _score_margin_ratio():
            return 0, []
    return best_angle, []


def prepare_orientation_normalized_file(file_path: str, file_name: str) -> OrientationNormalizedFile:
    """Create a temporary portrait-oriented copy for landscape scans before parsing."""
    if not _enabled():
        return OrientationNormalizedFile(file_path=file_path)
    source = Path(file_path)
    if not source.exists() or not source.is_file():
        return OrientationNormalizedFile(file_path=file_path)

    ext = Path(file_name or file_path).suffix.lower()
    if ext == ".pdf":
        return _normalize_pdf_orientation(file_path, file_name)
    if ext in _IMAGE_EXTENSIONS:
        return _normalize_image_orientation(file_path, file_name)
    return OrientationNormalizedFile(file_path=file_path)


def copy_orientation_normalized_file(file_path: str, file_name: str, target_path: str) -> list[str]:
    """Normalize orientation and copy the effective file to a caller-owned target path."""
    normalized = prepare_orientation_normalized_file(file_path, file_name)
    try:
        if normalized.file_path != target_path:
            shutil.copyfile(normalized.file_path, target_path)
        return list(normalized.warnings)
    finally:
        normalized.cleanup()


def write_orientation_display_copy(
    file_path: str,
    file_name: str,
    target_path: str,
) -> tuple[bool, list[str]]:
    """Write a persistent normalized display copy only when orientation changed."""
    normalized = prepare_orientation_normalized_file(file_path, file_name)
    try:
        if not normalized.changed:
            return False, list(normalized.warnings)
        shutil.copyfile(normalized.file_path, target_path)
        return True, list(normalized.warnings)
    finally:
        normalized.cleanup()


__all__ = [
    "ORIENTATION_ALGO_VERSION",
    "OrientationNormalizedFile",
    "copy_orientation_normalized_file",
    "display_copy_needs_regeneration",
    "legacy_normalized_display_paths",
    "normalized_display_path_for",
    "prepare_orientation_normalized_file",
    "write_orientation_display_copy",
]
