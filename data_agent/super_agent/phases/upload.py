"""Wizard phase: upload."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from pathlib import Path
from typing import Any, TYPE_CHECKING

from data_agent.core.config import GNC_RUNS_DIR
from data_agent.super_agent import helpers
from data_agent.super_agent.phases.base import PhaseHandlerBase, advance_wizard_phase
from data_agent.super_agent.schemas import (
    CreateSuperAgentRunRequest,
    StructuredReviewBundle,
    SuperAgentInputMode,
    SuperAgentMaterial,
    SuperAgentQualityReport,
    SuperAgentReviewMode,
    SuperAgentRoute,
    SuperAgentRouteDecision,
    SuperAgentRun,
    SuperAgentSkillTrace,
    SuperAgentTraceReport,
)

if TYPE_CHECKING:
    from data_agent.super_agent.execution_plan import ParsingPlan

logger = logging.getLogger(__name__)


class UploadPhaseHandler(PhaseHandlerBase):
    phase_id = "upload"
    wizard_step = 1

    def __init__(self, host):
        super().__init__(host)

    def apply_wizard_checkpoint(self, run, req) -> None:
        from data_agent.super_agent.schemas import SuperAgentInputMode

        if req.materials is not None:
            run.materials = req.materials
            run.input_mode = SuperAgentInputMode.UPLOAD
        if req.objective is not None:
            run.objective = req.objective
        if req.processing_mode is not None:
            run.processing_mode = req.processing_mode or "OPTIMAL"
        if req.materials is not None or req.objective is not None:
            artifact: dict[str, Any] = {}
            if req.materials is not None:
                artifact["material_count"] = len(req.materials)
            if req.objective is not None:
                artifact["objective"] = req.objective
            advance_wizard_phase(run, "upload", status="completed", artifact=artifact or None)

    def resolve_run_material_source(self, run_id: str, file_name: str) -> tuple[Path, str]:
        import tempfile

        run = self._host.get_run(run_id)
        if not run:
            raise ValueError(f"Super Agent run not found: {run_id}")
        target_name = (file_name or "").strip()
        if not target_name:
            raise ValueError("file_name 不能为空")
        for material in run.materials:
            if str(material.name or "") != target_name:
                continue
            display_path = str(getattr(material, "source_display_path", "") or "")
            if display_path:
                try:
                    return helpers._safe_super_agent_upload_path(display_path), material.name or target_name
                except ValueError:
                    logger.warning(
                        "[SuperAgent] normalized source display file missing; fallback to original: %s",
                        display_path,
                    )
            if material.file_path:
                source_path = helpers._safe_super_agent_upload_path(material.file_path)
                from data_agent.parsing.orientation import (
                    display_copy_needs_regeneration,
                    legacy_normalized_display_paths,
                    normalized_display_path_for,
                    write_orientation_display_copy,
                )

                normalized_path = normalized_display_path_for(source_path)
                if normalized_path.exists() and not display_copy_needs_regeneration(
                    source_path,
                    normalized_path,
                ):
                    return normalized_path, material.name or target_name
                for legacy_path in legacy_normalized_display_paths(source_path):
                    if legacy_path.exists() and legacy_path != normalized_path:
                        try:
                            legacy_path.unlink()
                        except OSError:
                            logger.warning(
                                "[SuperAgent] failed to remove legacy normalized display file: %s",
                                legacy_path,
                            )
                try:
                    changed, _warnings = write_orientation_display_copy(
                        str(source_path),
                        material.name or target_name,
                        str(normalized_path),
                    )
                    if changed:
                        return normalized_path, material.name or target_name
                except Exception as exc:
                    logger.warning(
                        "[SuperAgent] failed to prepare normalized source display file; fallback to original: %s",
                        exc,
                    )
                return source_path, material.name or target_name
            if material.content_base64:
                import base64

                raw = base64.b64decode(material.content_base64)
                suffix = Path(target_name).suffix or ".bin"
                tmp = Path(tempfile.mkdtemp(prefix="sa-src-")) / f"source{suffix}"
                tmp.write_bytes(raw)
                return tmp, material.name or target_name
        raise ValueError(f"Run 中未找到材料: {target_name}")

    def resolve_run_material_figure(
        self,
        run_id: str,
        file_name: str,
        block_id: str,
    ) -> Path:
        from data_agent.core.config import SUPER_AGENT_RUNS_DIR
        from data_agent.parsing.parse_figure_context import resolve_persisted_figure_path

        target_name = (file_name or "").strip()
        target_block = (block_id or "").strip()
        if not target_name or not target_block:
            raise ValueError("file_name 与 block_id 不能为空")
        path = resolve_persisted_figure_path(
            run_id,
            target_name,
            target_block,
            base_dir=SUPER_AGENT_RUNS_DIR,
        )
        if path is None:
            raise ValueError(f"未找到 figure 图片: {target_name} / {target_block}")
        return path