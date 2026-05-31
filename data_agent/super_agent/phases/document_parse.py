"""Wizard phase: document_parse."""

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
from data_agent.super_agent.phases.base import advance_wizard_phase
from data_agent.super_agent.phases.base import PhaseHandlerBase
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


class DocumentParsePhaseHandler(PhaseHandlerBase):
    phase_id = "document_parse"
    wizard_step = 3

    def __init__(self, host):
        super().__init__(host)

    def apply_wizard_checkpoint(self, run, req) -> None:
        if req.parse_preview is not None:
            run.parse_preview = req.parse_preview
            parse_artifact = req.parse_preview.get("parse_artifact") or {}
            if parse_artifact:
                run.structured_bundle.parse_artifact = parse_artifact
                run.structured_bundle.document_ir = parse_artifact.get("document_ir") or {}
            structure_summary = req.parse_preview.get("structure_summary")
            if isinstance(structure_summary, dict) and structure_summary.get("structure_ready"):
                section_tree = req.parse_preview.get("section_tree") or {}
                evidence_pool = req.parse_preview.get("evidence_pool") or {}
                if section_tree:
                    run.structured_bundle.section_tree = section_tree
                if evidence_pool:
                    run.structured_bundle.evidence_pool = evidence_pool
            artifact: dict[str, Any] = {"parse_preview": req.parse_preview}
            if parse_artifact:
                artifact["parse_artifact"] = parse_artifact
            if run.structured_bundle.section_tree or run.structured_bundle.evidence_pool:
                artifact["structured_bundle"] = {
                    "section_tree": run.structured_bundle.section_tree,
                    "evidence_pool": run.structured_bundle.evidence_pool,
                    "stats": run.structured_bundle.stats,
                }
            advance_wizard_phase(run, "document_parse", status="completed", artifact=artifact)

    def _attach_structure_preview(
        self,
        run: SuperAgentRun,
        preview: dict[str, Any],
        *,
        request: CreateSuperAgentRunRequest | None = None,
    ) -> dict[str, Any]:
        from data_agent.parsing.artifact_builder import (
            is_parse_artifact_complete,
            is_structure_artifact_complete,
        )

        parse_artifact = dict(preview.get("parse_artifact") or run.structured_bundle.parse_artifact or {})
        if parse_artifact:
            run.structured_bundle.parse_artifact = parse_artifact
            run.structured_bundle.document_ir = parse_artifact.get("document_ir") or {}

        if is_parse_artifact_complete(parse_artifact) and not is_structure_artifact_complete(
            run.structured_bundle.section_tree,
            run.structured_bundle.evidence_pool,
            document_ir=run.structured_bundle.document_ir,
            parse_artifact=parse_artifact,
        ):
            self._host.structure_materials(run, request=request)

        structure_summary = helpers.build_structure_summary(run.structured_bundle)
        preview["structure_summary"] = structure_summary
        if structure_summary.get("structure_ready"):
            preview["section_tree"] = run.structured_bundle.section_tree
            preview["evidence_pool"] = run.structured_bundle.evidence_pool
        return preview

    def execute_pipeline(self, ctx) -> None:
        from data_agent.super_agent.execution_plan import resolve_parsing_plan

        run = ctx.run
        decision = ctx.decision
        request = ctx.request
        resume = ctx.resume
        plan = resolve_parsing_plan(run, decision, request=request)
        ctx.plan = plan
        helpers.sync_wizard_parse_artifact(run)
        if not resume or not self._host.parse_phase_complete(run, plan):
            self.parse_materials(run, plan, request=request)
        self._host.checkpoint_run(run)

    def _effective_processing_mode(
        self,
        run: SuperAgentRun,
        classification: dict[str, Any] | None,
    ) -> str:
        if isinstance(classification, dict):
            parse_plan = classification.get("parse_plan")
            if isinstance(parse_plan, dict):
                default_mode = str(parse_plan.get("default_processing_mode") or "").strip()
                if default_mode:
                    return default_mode
        return run.processing_mode or "OPTIMAL"

    def enrich_preview_material_sources(
        self,
        preview: dict[str, Any],
        run: SuperAgentRun,
    ) -> None:
        from urllib.parse import quote

        materials = preview.get("materials")
        if not isinstance(materials, list):
            return
        by_name = {str(item.name or ""): item for item in run.materials if str(item.name or "").strip()}
        for item in materials:
            if not isinstance(item, dict):
                continue
            file_name = str(item.get("file_name") or "")
            material = by_name.get(file_name)
            if not material:
                continue
            if material.file_id:
                item["file_id"] = material.file_id
            if material.upload_id:
                item["upload_id"] = material.upload_id
            if material.file_path:
                item["source_download_url"] = (
                    f"/api/v1/super-agent/runs/{run.run_id}/materials/source"
                    f"?file_name={quote(file_name)}"
                )
            blocks = item.get("blocks")
            if isinstance(blocks, list):
                for block in blocks:
                    if not isinstance(block, dict):
                        continue
                    block_id = str(block.get("id") or "")
                    if not block_id:
                        continue
                    block_type = str(block.get("block_type") or "").lower()
                    content = str(block.get("content") or block.get("markdown") or "").strip()
                    bbox = block.get("bbox")
                    has_bbox = isinstance(bbox, list) and len(bbox) >= 4
                    has_figure_asset = bool(str(block.get("image_ref") or "").strip())
                    from data_agent.parsing.figure_text import looks_like_image_ref

                    is_visual_image = block_type in {"figure", "image"} or (
                        has_bbox and looks_like_image_ref(content)
                    )
                    if not is_visual_image and not has_figure_asset and not block.get("image_description"):
                        continue
                    block["image_url"] = (
                        f"/api/v1/super-agent/runs/{run.run_id}/materials/figures"
                        f"?file_name={quote(file_name)}&block_id={quote(block_id)}"
                    )

    def preview_parse_from_run(
        self,
        run_id: str,
        *,
        force_reparse: bool = False,
        request: CreateSuperAgentRunRequest | None = None,
    ) -> dict[str, Any]:
        """document_parse (step 3): tiered L2 parse preview using saved classification (no re-classify)."""
        from data_agent.parsing.artifact_builder import is_parse_artifact_complete

        run = self._host.get_run(run_id)
        if not run:
            raise ValueError(f"Super Agent run not found: {run_id}")
        if not run.materials:
            raise ValueError(f"Super Agent run has no materials to preview: {run_id}")

        known_classification = run.classification if isinstance(run.classification, dict) else None
        if not helpers._has_saved_classification(known_classification):
            raise ValueError("请先完成材料智能识别（classify_and_route）")

        helpers.sync_wizard_parse_artifact(run)
        parse_artifact = dict(run.structured_bundle.parse_artifact or {})
        if not parse_artifact and isinstance(run.parse_preview, dict):
            parse_artifact = dict(run.parse_preview.get("parse_artifact") or {})

        if force_reparse or not is_parse_artifact_complete(parse_artifact):
            from data_agent.parsing.parse_preview_progress import report_progress

            report_progress(25, "正在 MinerU 解析材料…")
            uploads: list[tuple[str, bytes]] = []
            for index, material in enumerate(run.materials):
                try:
                    raw = helpers._material_raw_bytes(material)
                except Exception as exc:
                    raise ValueError(f"材料读取失败 {material.name or index}: {exc}") from exc
                uploads.append((material.name or f"material-{index}.txt", raw))

            preview = self.preview_parse_materials(
                uploads,
                objective=run.objective,
                processing_mode=self._effective_processing_mode(run, known_classification),
                known_classification=known_classification,
                run_id=run_id,
            )
            self.enrich_preview_material_sources(preview, run)
        else:
            preview = dict(run.parse_preview) if isinstance(run.parse_preview, dict) else {}
            if not preview:
                preview = {
                    "parse_artifact": parse_artifact,
                    "document_ir": parse_artifact.get("document_ir") or run.structured_bundle.document_ir,
                    "batch_summary": parse_artifact.get("batch_summary") or {},
                    "materials": [],
                }
            self.enrich_preview_material_sources(preview, run)

        from data_agent.parsing.parse_preview_progress import report_progress

        report_progress(92, "正在构建章节结构…")
        preview = self._attach_structure_preview(run, preview, request=request)
        from data_agent.super_agent.post_parse_router import apply_post_parse_route

        preview = apply_post_parse_route(run, preview)
        run.parse_preview = preview
        parse_artifact = preview.get("parse_artifact") or {}
        if parse_artifact:
            run.structured_bundle.parse_artifact = parse_artifact
            run.structured_bundle.document_ir = parse_artifact.get("document_ir") or {}
        artifact: dict[str, Any] = {"parse_artifact": parse_artifact} if parse_artifact else {}
        if preview.get("structure_summary"):
            artifact["structure_summary"] = preview["structure_summary"]
        advance_wizard_phase(
            run,
            "document_parse",
            status="completed",
            artifact=artifact or None,
        )
        self._host.checkpoint_run(run)
        return preview

    def parse_materials(
        self,
        run: SuperAgentRun,
        plan: ParsingPlan,
        *,
        request: CreateSuperAgentRunRequest | None = None,
    ) -> None:
        """L3: single parsing pass according to plan; results cached on run."""
        from data_agent.parsing.artifact_builder import (
            is_parse_artifact_complete,
            is_structure_artifact_complete,
        )

        helpers.sync_wizard_parse_artifact(run)
        parse_artifact = dict(run.structured_bundle.parse_artifact or {})
        parse_ready = is_parse_artifact_complete(parse_artifact)
        structure_ready = is_structure_artifact_complete(
            run.structured_bundle.section_tree,
            run.structured_bundle.evidence_pool,
            document_ir=run.structured_bundle.document_ir,
            parse_artifact=parse_artifact,
        )

        if plan.bootstrap_review_plus:
            if not request:
                raise ValueError("bootstrap_review_plus 需要 execute 请求上下文")
            self._host.bootstrap_review_plus_task(run, request)
            if run.source_review_id:
                from data_agent.review_plus.service import get_review_plus_service
                from data_agent.super_agent.phases.document_review.sync import ensure_review_plus_parsed

                rp_svc = get_review_plus_service()
                task = rp_svc.get_review(run.source_review_id)
                if task:
                    ensure_review_plus_parsed(rp_svc, task, run)
            return
        if parse_ready and not structure_ready and (plan.run_structure_parse or plan.reuse_review_plus_parse):
            self._host.structure_materials(run, request=request)
            return
        if parse_ready and structure_ready:
            return
        if plan.run_structure_parse:
            self._host.structure_materials(run, request=request)
            return
        if plan.reuse_review_plus_parse and run.source_review_id:
            self._host.structure_materials(run, request=request)

    def extract_preview_content_from_parsed_item(
        self,
        item: dict[str, Any],
        *,
        preview_max_chars: int = helpers._PARSE_CONTENT_PREVIEW_MAX_CHARS,
        markdown_max_chars: int = helpers._PARSE_CONTENT_MARKDOWN_MAX_CHARS,
    ) -> tuple[str, str, str, bool, list[str]]:
        document = item.get("document") if isinstance(item.get("document"), dict) else {}
        blocks = [block for block in (document.get("blocks") or []) if isinstance(block, dict)]
        raw_parts: list[str] = []
        preview_parts: list[str] = []
        preview_len = 0
        for block in blocks:
            raw_text = str(block.get("text") or "").strip()
            if raw_text:
                raw_parts.append(raw_text)
            display = helpers._block_display_text(block)
            if not display or preview_len >= preview_max_chars:
                continue
            remaining = preview_max_chars - preview_len
            if len(display) > remaining:
                display = display[:remaining]
            preview_parts.append(display)
            preview_len += len(display) + 2

        content = str(item.get("content") or "") or "\n".join(raw_parts)
        content_preview = "\n\n".join(preview_parts)
        if not content_preview.strip() and content:
            content_preview = content[:preview_max_chars]
        content_markdown, markdown_truncated = helpers._build_markdown_from_blocks(
            blocks,
            max_chars=markdown_max_chars,
        )
        if not content_markdown.strip() and content:
            content_markdown = content[:markdown_max_chars]
            markdown_truncated = len(content) > markdown_max_chars
        from data_agent.parsing.parse_artifacts import is_info_only_parse_warning

        warnings = [
            warning
            for warning in list(item.get("warnings") or document.get("warnings") or [])
            if not is_info_only_parse_warning(warning)
        ]
        return content, content_preview, content_markdown, markdown_truncated, warnings

    def materials_preview_from_parse_artifact(
        self,
        parse_artifact: dict[str, Any],
        *,
        role_by_name: dict[str, Any],
        parser_default: str,
        processing_mode: str,
    ) -> list[dict[str, Any]]:
        from data_agent.review_plus.schemas import ReviewPlusMaterialRole
        from data_agent.services.task_classifier import resolve_parsing_tier

        parsed_by_name = {
            str(item.get("file_name") or ""): item
            for item in (parse_artifact.get("parsed_documents") or [])
            if isinstance(item, dict)
        }
        file_results_by_name = {
            str(item.get("file_name") or ""): item
            for item in (parse_artifact.get("file_results") or [])
            if isinstance(item, dict)
        }

        materials_preview: list[dict[str, Any]] = []
        for file_name in sorted(set(parsed_by_name) | set(file_results_by_name)):
            parsed_item = parsed_by_name.get(file_name) or {}
            file_result = file_results_by_name.get(file_name) or {}
            role_item = role_by_name.get(file_name)
            role_value = role_item.role if role_item else ReviewPlusMaterialRole.UNKNOWN.value
            tier = resolve_parsing_tier(role_value, file_name, default_parser_type=parser_default)
            intended_processing_mode = str(tier.get("processing_mode") or processing_mode)
            content, content_preview, content_markdown, markdown_truncated, warnings = (
                self.extract_preview_content_from_parsed_item(parsed_item)
            )
            if not content_preview.strip() and warnings:
                content_preview = "\n".join(warnings[:5])[:helpers._PARSE_CONTENT_PREVIEW_MAX_CHARS]
            ir_stats = file_result.get("document_ir_stats") or {}
            parse_status = str(
                file_result.get("parse_status")
                or parsed_item.get("parse_status")
                or ""
            )
            capability_passed = file_result.get("capability_passed")
            if capability_passed is None:
                capability_passed = parse_status == "ok" and not bool(file_result.get("degraded"))
            document = parsed_item.get("document") if isinstance(parsed_item.get("document"), dict) else {}
            raw_blocks = [block for block in (document.get("blocks") or []) if isinstance(block, dict)]
            calibration_records = [
                record for record in (document.get("calibration_records") or []) if isinstance(record, dict)
            ]
            preview_blocks = helpers._serialize_preview_blocks(
                raw_blocks,
                calibration_records=calibration_records,
            )
            materials_preview.append(
                {
                    "file_name": file_name,
                    "role": role_value,
                    "role_confidence": float(role_item.confidence if role_item else 0.0),
                    "role_reason": str(role_item.reason if role_item else ""),
                    "parsing_tier": str(tier.get("tier") or "standard"),
                    "parser_type": str(tier.get("parser_type") or parser_default),
                    "processing_mode": intended_processing_mode,
                    "parse_status": parse_status,
                    "parser_name": str(
                        file_result.get("parser_selected")
                        or parsed_item.get("parser_name")
                        or ""
                    ),
                    "content_preview": content_preview,
                    "content_markdown": content_markdown,
                    "content_markdown_truncated": markdown_truncated,
                    "content_length": len(content),
                    "line_count": len([line for line in content.splitlines() if line.strip()]),
                    "source_file_type": Path(file_name).suffix.lower().lstrip("."),
                    "page_count": int(ir_stats.get("page_count") or 0),
                    "blocks": preview_blocks,
                    "parse_artifact_subset": helpers._build_parse_artifact_subset(parsed_item, file_result),
                    "warnings": warnings,
                    "parser_trace": [
                        {
                            "kind": "parsing_tier",
                            "tier": tier.get("tier"),
                            "role": role_value,
                            "parser_type": tier.get("parser_type"),
                            "processing_mode": tier.get("processing_mode"),
                        },
                        *list(parse_artifact.get("parser_trace") or []),
                    ],
                    "capability_passed": bool(capability_passed),
                    "degraded": bool(file_result.get("degraded")),
                    "document_ir_stats": ir_stats,
                }
            )
        return materials_preview

    def preview_parse_materials(
        self,
        uploads: list[tuple[str, bytes]],
        *,
        objective: str = "",
        processing_mode: str = "OPTIMAL",
        parser_type: str = "auto",
        mineru_parse_mode: str = "",
        known_classification: dict[str, Any] | None = None,
        run_id: str = "",
    ) -> dict[str, Any]:
        """L2 parse preview: build parse-only artifact aligned with Review-Plus Step 3."""
        import tempfile
        from types import SimpleNamespace

        from data_agent.parsing.material_preview import extract_material_preview
        from data_agent.core.config import SUPER_AGENT_RUNS_DIR
        from data_agent.review_plus.schemas import ReviewPlusMaterialRole
        from data_agent.parsing.parse_artifacts import build_parse_only_artifact_from_materials
        from data_agent.services.task_classifier import classify_batch, resolve_parsing_tier

        if not uploads:
            raise ValueError("请至少上传一个文件")

        parser_default = (parser_type or "auto").strip().lower()
        mineru_mode = (mineru_parse_mode or "").strip()
        if processing_mode and processing_mode.upper() != "OPTIMAL":
            from data_agent.agents.format_guard.mode_policy import resolve_parser_type

            first_name = uploads[0][0] or "material.txt"
            parser_default = resolve_parser_type(first_name, processing_mode)

        preview_materials: list[dict[str, str]] = []
        saved_files: list[tuple[str, Path]] = []

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            for filename, raw_content in uploads:
                safe_name = (filename or "material.txt").strip() or "material.txt"
                file_path = tmp_path / safe_name
                file_path.write_bytes(raw_content or b"")
                saved_files.append((safe_name, file_path))
                preview = extract_material_preview(str(file_path), safe_name)
                preview_materials.append(
                    {
                        "file_name": safe_name,
                        "file_path": str(file_path),
                        "content": preview,
                        "preview_content": preview,
                    }
                )

            if helpers._has_saved_classification(known_classification):
                known_roles = known_classification.get("material_roles")
                role_by_name: dict[str, SimpleNamespace] = {}
                if isinstance(known_roles, list):
                    role_by_name = {
                        str(item.get("file_name") or ""): SimpleNamespace(
                            file_name=str(item.get("file_name") or ""),
                            role=str(item.get("role") or ReviewPlusMaterialRole.UNKNOWN.value),
                            confidence=float(item.get("confidence") or 0.0),
                            reason=str(item.get("reason") or ""),
                        )
                        for item in known_roles
                        if isinstance(item, dict) and str(item.get("file_name") or "").strip()
                    }
                recommended_route = str(
                    known_classification.get("recommended_route") or "auto"
                )
                domain = str(known_classification.get("domain") or "通用审查")
                classification_reason = str(
                    known_classification.get("reason") or objective or "复用步骤 2 识别结果"
                )
                classification_confidence = float(known_classification.get("confidence") or 0.0)
                classification_roles_payload = [
                    {
                        "file_name": item.file_name,
                        "role": item.role,
                        "confidence": item.confidence,
                        "reason": item.reason,
                    }
                    for item in role_by_name.values()
                ]
            else:
                classification = classify_batch(preview_materials, objective=objective)
                role_by_name = {item.file_name: item for item in classification.material_roles}
                route_map = {
                    "review_plus": "review_plus",
                    "gnc_review": "gnc_review",
                    "parse_only": "smart",
                }
                recommended_route = route_map.get(classification.route, classification.route)
                domain = "GNC/控制" if classification.route == "gnc_review" else "通用审查"
                classification_reason = classification.reason
                classification_confidence = classification.confidence
                classification_roles_payload = [
                    item.model_dump(mode="json") for item in classification.material_roles
                ]

            parse_inputs: list[dict[str, Any]] = []
            figure_storage_dir = ""
            if run_id:
                figure_storage_dir = str(SUPER_AGENT_RUNS_DIR / run_id / "figures")
            material_roles_map: dict[str, Any] = {}
            for safe_name, file_path in saved_files:
                role_item = role_by_name.get(safe_name)
                role_value = role_item.role if role_item else ReviewPlusMaterialRole.UNKNOWN.value
                tier = resolve_parsing_tier(role_value, safe_name, default_parser_type=parser_default)
                intended_processing_mode = str(tier.get("processing_mode") or processing_mode)
                material_roles_map[safe_name] = role_value
                parser_for_item = str(tier.get("parser_type") or parser_default)
                if mineru_mode and parser_default in {"mineru", "mineru_agent", "mineru_via_pdf"}:
                    parser_for_item = parser_default
                parse_inputs.append(
                    {
                        "file_path": str(file_path),
                        "file_name": safe_name,
                        "parser_type": parser_for_item,
                        "processing_mode": intended_processing_mode,
                        "mineru_parse_mode": mineru_mode,
                        "skip_enhancement": True,
                        "parse_preview": True,
                        "run_id": run_id,
                        "figure_storage_dir": figure_storage_dir,
                    }
                )

            parse_only = build_parse_only_artifact_from_materials(parse_inputs)
            parse_payload = parse_only.model_dump(mode="json")
            parse_payload["pipeline_step"] = "document_parse"
            materials_preview = self.materials_preview_from_parse_artifact(
                parse_payload,
                role_by_name=role_by_name,
                parser_default=parser_default,
                processing_mode=processing_mode,
            )
            batch_summary = parse_payload.get("batch_summary") or {}
            material_count = len(materials_preview)
            parsed_ok = int(batch_summary.get("parsed_count") or 0)
            degraded_count = int(batch_summary.get("degraded_count") or 0) + int(
                batch_summary.get("failed_count") or 0
            )

        return {
            "parse_artifact": parse_payload,
            "document_ir": parse_payload.get("document_ir") or {},
            "batch_summary": batch_summary,
            "classification": {
                "doc_type": "批量材料包" if len(uploads) > 1 else "单文档",
                "domain": domain,
                "recommended_route": recommended_route,
                "reason": classification_reason,
                "confidence": classification_confidence,
                "material_roles": classification_roles_payload,
                "classifier": "shared_task_classifier",
            },
            "materials": materials_preview,
            "summary": {
                "material_count": material_count,
                "parsed_ok": parsed_ok,
                "degraded_count": degraded_count,
            },
        }

    def execute_parse_for_run(
        self,
        run_id: str,
        *,
        include_structure: bool = False,
        force_reparse: bool = False,
        request: CreateSuperAgentRunRequest | None = None,
    ) -> dict[str, Any]:
        """Independent parse API: produce parse-only artifact (optional structure) for a run."""
        from data_agent.parsing.artifact_builder import (
            is_parse_artifact_complete,
            is_structure_artifact_complete,
        )

        run = self._host.get_run(run_id)
        if not run:
            raise ValueError(f"Super Agent run not found: {run_id}")
        if not run.materials:
            raise ValueError(f"Super Agent run has no materials to parse: {run_id}")

        known_classification = run.classification if isinstance(run.classification, dict) else None
        if not helpers._has_saved_classification(known_classification):
            raise ValueError("请先完成材料智能识别（classify_and_route）")

        parse_artifact = dict(run.structured_bundle.parse_artifact or {})
        if not parse_artifact and isinstance(run.parse_preview, dict):
            parse_artifact = dict(run.parse_preview.get("parse_artifact") or {})

        if force_reparse or not is_parse_artifact_complete(parse_artifact):
            preview = self.preview_parse_from_run(run_id, force_reparse=True, request=request)
            parse_artifact = dict(preview.get("parse_artifact") or {})
        else:
            preview = run.parse_preview if isinstance(run.parse_preview, dict) else {}
            if not preview:
                preview = {
                    "parse_artifact": parse_artifact,
                    "document_ir": parse_artifact.get("document_ir") or run.structured_bundle.document_ir,
                    "batch_summary": parse_artifact.get("batch_summary") or {},
                    "materials": [],
                }
            preview = self._attach_structure_preview(run, preview, request=request)
            run.parse_preview = preview
            advance_wizard_phase(
                run,
                "document_parse",
                status="completed",
                artifact={"parse_artifact": parse_artifact} if parse_artifact else None,
            )

        structured_bundle: StructuredReviewBundle | None = None
        if include_structure and not is_structure_artifact_complete(
            run.structured_bundle.section_tree,
            run.structured_bundle.evidence_pool,
            document_ir=run.structured_bundle.document_ir,
            parse_artifact=parse_artifact,
        ):
            structured_bundle = self._host.structure_materials(run, request=request)
        elif include_structure:
            structured_bundle = run.structured_bundle

        self._host.checkpoint_run(run)

        return {
            "run_id": run.run_id,
            "parse_artifact": parse_artifact,
            "document_ir": parse_artifact.get("document_ir") or run.structured_bundle.document_ir or {},
            "batch_summary": parse_artifact.get("batch_summary") or {},
            "materials": list(preview.get("materials") or []),
            "structured_bundle": structured_bundle,
        }