"""Structure materials skill for document_review phase."""

from __future__ import annotations

import asyncio
import time
from typing import Any, TYPE_CHECKING

from data_agent.super_agent import helpers
from data_agent.super_agent.schemas import (
    CreateSuperAgentRunRequest,
    StructuredReviewBundle,
    SuperAgentInputMode,
    SuperAgentRun,
    SuperAgentSkillTrace,
)

if TYPE_CHECKING:
    from data_agent.super_agent.phases.base import RunHost


def _material_content_from_parsed_item(item: dict[str, Any]) -> str:
    document = item.get("document") if isinstance(item.get("document"), dict) else {}
    blocks = document.get("blocks") or []
    parts: list[str] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        text = str(
            block.get("text")
            or block.get("markdown")
            or block.get("table_markdown")
            or block.get("vision_description")
            or ""
        ).strip()
        if text:
            parts.append(text)
    return "\n\n".join(parts).strip()


def _materials_from_parse_artifact(parse_artifact: dict[str, Any]) -> list[dict[str, Any]]:
    materials: list[dict[str, Any]] = []
    seen: set[str] = set()
    file_results = {
        str(item.get("file_name") or item.get("name") or ""): item
        for item in (parse_artifact.get("file_results") or [])
        if isinstance(item, dict)
    }
    for item in parse_artifact.get("parsed_documents") or []:
        if not isinstance(item, dict):
            continue
        document = item.get("document") if isinstance(item.get("document"), dict) else {}
        name = str(
            item.get("file_name")
            or document.get("file_name")
            or item.get("name")
            or "document"
        ).strip()
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        file_result = file_results.get(name) or {}
        content = str(item.get("content") or item.get("text") or "").strip()
        if not content:
            content = _material_content_from_parsed_item(item)
        materials.append(
            {
                "name": name,
                "file_type": str(file_result.get("file_type") or document.get("file_type") or ""),
                "content": content,
                "content_preview": content[:1200],
                "file_path": str(item.get("file_path") or file_result.get("file_path") or ""),
                "parser_type": str(item.get("parser_name") or document.get("parser_name") or "parse_artifact"),
                "role": str(item.get("role") or "subject_document"),
                "parse_status": str(item.get("parse_status") or document.get("parse_status") or ""),
            }
        )
    return materials


def _backfill_materials_from_parse_artifact(bundle: StructuredReviewBundle) -> None:
    if bundle.materials:
        stats = dict(bundle.stats or {})
        stats.setdefault("material_count", len(bundle.materials))
        bundle.stats = stats
        return
    parse_artifact = bundle.parse_artifact or {}
    if not isinstance(parse_artifact, dict) or not parse_artifact:
        return
    materials = _materials_from_parse_artifact(parse_artifact)
    if not materials:
        return
    bundle.materials = materials
    stats = dict(bundle.stats or {})
    stats["material_count"] = len(materials)
    bundle.stats = stats


class StructureMixin:
    _host: RunHost

    def structure_materials(
        self,
        run: SuperAgentRun,
        *,
        request: CreateSuperAgentRunRequest | None = None,
    ) -> StructuredReviewBundle:
        started = time.perf_counter()
        existing_trace = self._host.latest_skill_trace(run, "structure_materials")
        _backfill_materials_from_parse_artifact(run.structured_bundle)
        stats = run.structured_bundle.stats or {}
        if (
            existing_trace
            and existing_trace.status == "completed"
            and (stats.get("material_count") or stats.get("section_count") or stats.get("evidence_count"))
        ):
            skip_trace = SuperAgentSkillTrace(
                skill_id="structure_materials",
                agent_id="data-agent:structuring_agent",
                tool_name="structure_materials",
                status="skipped",
                input_summary={"source_review_id": run.source_review_id, "resume_skip": True},
                output_summary=dict(stats),
            )
            skip_trace.elapsed_ms = 0
            run.skill_traces.append(skip_trace)
            return run.structured_bundle

        trace = SuperAgentSkillTrace(
            skill_id="structure_materials",
            agent_id="data-agent:structuring_agent",
            tool_name="structure_materials",
            status="running",
            input_summary={"input_mode": run.input_mode.value, "source_review_id": run.source_review_id},
        )
        try:
            from data_agent.parsing.artifact_builder import (
                is_parse_artifact_complete,
                is_structure_artifact_complete,
            )

            materials: list[dict[str, Any]] = []
            if run.input_mode == SuperAgentInputMode.EXISTING_REVIEW_PLUS and run.source_review_id:
                from data_agent.review_plus.service import get_review_plus_service

                task = get_review_plus_service().get_review(run.source_review_id)
                if not task:
                    raise ValueError(f"Review-Plus task not found: {run.source_review_id}")
                parse_artifact = getattr(task, "parse_artifact", {}) or {}
                has_structure = is_structure_artifact_complete(
                    getattr(task, "section_tree", {}) or {},
                    getattr(task, "evidence_pool", {}) or {},
                    document_ir=getattr(task, "document_ir", {}) or {},
                    parse_artifact=parse_artifact,
                )
                if not has_structure and not is_parse_artifact_complete(parse_artifact):
                    raise ValueError(
                        f"Review-Plus 任务尚未完成材料解析，请先调用 parse 步骤: {run.source_review_id}"
                    )
                materials = [material.model_dump() for material in task.materials]
                run.structured_bundle = StructuredReviewBundle(
                    materials=helpers._summarize_task_materials(task),
                    parser_traces=list(getattr(task, "parser_traces", []) or []),
                    section_tree=getattr(task, "section_tree", {}) or {},
                    evidence_pool=getattr(task, "evidence_pool", {}) or {},
                    document_ir=getattr(task, "document_ir", {}) or {},
                    parse_artifact=getattr(task, "parse_artifact", {}) or {},
                    chunks=list(getattr(task, "parsed_documents", []) or []),
                    check_items=[item.model_dump() for item in getattr(task, "check_items", []) or []],
                    stats={
                        "material_count": len(getattr(task, "materials", []) or []),
                        "check_item_count": len(getattr(task, "check_items", []) or []),
                        "section_count": len((getattr(task, "section_tree", {}) or {}).get("sections", [])),
                        "evidence_count": len((getattr(task, "evidence_pool", {}) or {}).get("evidences", [])),
                    },
                    warnings=[warning for material in task.materials for warning in (material.warnings or [])],
                    parser_fallback_logs=[
                        item
                        for item in (getattr(task, "parser_traces", []) or [])
                        if item.get("kind") == "parser_fallback"
                    ],
                    self_healing_records=[
                        item
                        for item in (getattr(task, "parser_traces", []) or [])
                        if item.get("kind") == "self_healing"
                    ],
                )
            elif request or run.materials:
                materials = []
                source_materials = request.materials if request else run.materials
                for index, item in enumerate(source_materials, start=1):
                    material, material_warnings = helpers._persist_upload_material(run.run_id, item, index=index)
                    trace.warnings.extend(material_warnings)
                    materials.append(material)

            from data_agent.parsing.parse_artifacts import (
                build_structure_artifact,
                merge_parse_and_structure,
            )
            from data_agent.parsing.structuring.preview import preview_document_chunks

            parse_artifact = run.structured_bundle.parse_artifact or {}
            if is_structure_artifact_complete(
                run.structured_bundle.section_tree,
                run.structured_bundle.evidence_pool,
                document_ir=run.structured_bundle.document_ir,
                parse_artifact=parse_artifact,
            ):
                stats = dict(run.structured_bundle.stats or {})
                stats["reuse_source"] = "existing_review_plus_parse_artifact"
                run.structured_bundle.stats = stats
            elif is_parse_artifact_complete(parse_artifact) and not is_structure_artifact_complete(
                run.structured_bundle.section_tree,
                run.structured_bundle.evidence_pool,
                document_ir=run.structured_bundle.document_ir,
                parse_artifact=parse_artifact,
            ):
                structure = build_structure_artifact(parse_artifact)
                merged = merge_parse_and_structure(parse_artifact, structure)
                merged_payload = merged.model_dump(mode="json")
                stats = dict(run.structured_bundle.stats or {})
                stats.update(
                    {
                        "section_count": len((merged_payload.get("section_tree") or {}).get("sections", [])),
                        "evidence_count": len((merged_payload.get("evidence_pool") or {}).get("evidences", [])),
                        "reuse_source": "parse_artifact_structure_only",
                    }
                )
                run.structured_bundle = StructuredReviewBundle(
                    materials=run.structured_bundle.materials
                    or _materials_from_parse_artifact(merged_payload),
                    parser_traces=run.structured_bundle.parser_traces,
                    section_tree=merged_payload.get("section_tree") or {},
                    evidence_pool=merged_payload.get("evidence_pool") or {},
                    document_ir=merged_payload.get("document_ir") or {},
                    parse_artifact=merged_payload,
                    chunks=run.structured_bundle.chunks,
                    extracted_parameters=merged_payload.get("extracted_parameters") or [],
                    extracted_objects=merged_payload.get("extracted_objects") or [],
                    trace_link_candidates=merged_payload.get("trace_link_candidates") or [],
                    stats=stats,
                    warnings=list(structure.warnings or []),
                )
                _backfill_materials_from_parse_artifact(run.structured_bundle)
            elif materials and not is_structure_artifact_complete(
                run.structured_bundle.section_tree,
                run.structured_bundle.evidence_pool,
                document_ir=run.structured_bundle.document_ir,
                parse_artifact=run.structured_bundle.parse_artifact,
            ):
                parse_artifact = run.structured_bundle.parse_artifact or {}
                if not is_parse_artifact_complete(parse_artifact):
                    from data_agent.parsing.parse_artifacts import build_parse_only_artifact_from_materials

                    parse_inputs = [
                        {
                            "file_path": mat.get("file_path", ""),
                            "file_name": mat.get("name", "") or mat.get("file_name", ""),
                            "parser_type": mat.get("parser_type"),
                            "processing_mode": mat.get("processing_mode"),
                        }
                        for mat in materials
                        if mat.get("file_path")
                    ]
                    if not parse_inputs:
                        raise ValueError("structure_materials 需要先完成 parse-only 解析")
                    parse_only = build_parse_only_artifact_from_materials(parse_inputs)
                    parse_artifact = parse_only.model_dump(mode="json")
                    parse_artifact["pipeline_step"] = "document_parse"

                result = asyncio.run(
                    preview_document_chunks(
                        materials=materials,
                        strategy="code_based",
                        review_scope="super_agent",
                        parse_artifact=parse_artifact,
                    )
                )
                stats = {**run.structured_bundle.stats, **(result.get("stats") or {})}
                stats.setdefault("material_count", len(materials))
                stats.setdefault("check_item_count", len(run.structured_bundle.check_items))
                run.structured_bundle = StructuredReviewBundle(
                    materials=materials if materials else run.structured_bundle.materials,
                    parser_traces=run.structured_bundle.parser_traces,
                    section_tree=result.get("section_tree") or {},
                    evidence_pool=result.get("evidence_pool") or {},
                    document_ir=result.get("document_ir") or {},
                    parse_artifact=result.get("parse_artifact") or {},
                    chunks=result.get("chunks") or [],
                    extracted_parameters=result.get("extracted_parameters") or [],
                    extracted_objects=result.get("extracted_objects") or [],
                    trace_link_candidates=result.get("trace_link_candidates") or [],
                    stats=stats,
                    warnings=result.get("warnings") or [],
                )

            trace.status = "completed"
            trace.output_summary = dict(run.structured_bundle.stats)
            self._host.mark_step_completed(run, "structure_materials")
        except Exception as exc:
            trace.status = "failed"
            trace.warnings.append(str(exc))
            raise
        finally:
            trace.elapsed_ms = int((time.perf_counter() - started) * 1000)
            run.skill_traces.append(trace)
        return run.structured_bundle
