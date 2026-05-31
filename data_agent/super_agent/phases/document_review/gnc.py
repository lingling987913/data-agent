"""GNC review delegation for document_review phase."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any, TYPE_CHECKING

from data_agent.core.config import GNC_RUNS_DIR
from data_agent.super_agent.schemas import (
    CreateSuperAgentRunRequest,
    SuperAgentInputMode,
    SuperAgentReviewMode,
    SuperAgentRun,
    SuperAgentSkillTrace,
)

if TYPE_CHECKING:
    from data_agent.super_agent.phases.base import RunHost

logger = logging.getLogger(__name__)


class GncMixin:
    _host: RunHost

    def run_gnc_review(
        self,
        run: SuperAgentRun,
        *,
        request: CreateSuperAgentRunRequest | None = None,
        allow_missing: bool = False,
    ) -> dict[str, Any]:
        """Delegate to the satellite GNC workflow when it is installed."""
        started = time.perf_counter()
        trace = SuperAgentSkillTrace(
            skill_id="run_gnc_review",
            agent_id="data-agent:gnc_delegate_agent",
            tool_name="run_gnc_review",
            status="running",
            input_summary={
                "review_id": run.source_review_id,
                "review_mode": run.review_mode.value,
                "allow_missing": allow_missing,
            },
        )
        run.skill_traces.append(trace)
        if hasattr(self._host, "checkpoint_run"):
            self._host.checkpoint_run(run)
        try:
            if run.input_mode == SuperAgentInputMode.EXISTING_GNC_REVIEW and run.source_review_id:
                existing_result = self.load_existing_gnc_result(run.source_review_id)
                if existing_result:
                    run.gnc_review_result = existing_result
                    if run.route_decision:
                        run.route_decision.gnc_review_id = run.source_review_id
                    trace.status = "completed"
                    trace.output_summary = {
                        "status": existing_result.get("status"),
                        "gnc_review_id": run.source_review_id,
                        "source": "existing_gnc_review",
                    }
                    return run.gnc_review_result

            try:
                from data_agent.integrations.satellite_review.gnc_workflow import run_gnc_design_review
            except ModuleNotFoundError as exc:
                if exc.name != "data_agent.integrations.satellite_review.gnc_workflow":
                    raise
                message = "GNC review workflow 尚未在 data-agent 中实现"
                trace.status = "skipped" if allow_missing else "failed"
                trace.warnings.append(message)
                if not allow_missing:
                    raise ValueError(message) from exc
                run.gnc_review_result = {
                    "status": "skipped",
                    "reason": message,
                    "review_mode": run.review_mode.value,
                }
                return run.gnc_review_result
            except ImportError:
                run_gnc_design_review = None

            if not run.structured_bundle.materials:
                self._host.structure_materials(run, request=request)
            if run.skill_traces and run.skill_traces[-1] is not trace:
                run.skill_traces = [existing for existing in run.skill_traces if existing is not trace]
                run.skill_traces.append(trace)
                if hasattr(self._host, "checkpoint_run"):
                    self._host.checkpoint_run(run)
            materials = self.gnc_materials_for_run(run)
            if run.review_mode == SuperAgentReviewMode.SINGLE_DOC and len(materials) != 1:
                raise ValueError("single_doc 模式要求恰好 1 份文档")
            if run.review_mode == SuperAgentReviewMode.MULTI_DOC and len(materials) < 2:
                raise ValueError("multi_doc 模式要求至少 2 份文档")

            payload = {
                "run_id": run.run_id,
                "review_id": run.source_review_id,
                "objective": run.objective,
                "review_mode": run.review_mode.value,
                "materials": materials,
                "structured_bundle": run.structured_bundle.model_dump(mode="json"),
                "cross_document_consistency": run.review_mode
                in {SuperAgentReviewMode.MULTI_DOC, SuperAgentReviewMode.FULL},
            }
            task_fn = lambda: self.run_gnc_design_review(payload, runner=run_gnc_design_review)
            if hasattr(self._host, "run_with_periodic_checkpoints"):
                result = self._host.run_with_periodic_checkpoints(run, task_fn)
            else:
                result = task_fn()
            if not isinstance(result, dict):
                result = {"result": result}
            result.setdefault("status", "completed")
            result.setdefault("review_mode", run.review_mode.value)
            run.gnc_review_result = result
            gnc_review_id = str(result.get("gnc_review_id") or result.get("review_id") or "")
            if gnc_review_id and run.route_decision:
                run.route_decision.gnc_review_id = gnc_review_id
            trace.status = "completed"
            trace.output_summary = {
                "status": result.get("status"),
                "gnc_review_id": gnc_review_id,
                "finding_count": len(result.get("findings") or []),
                "conflict_count": len(result.get("conflicts") or result.get("cross_document_conflicts") or []),
            }
            self._host.mark_step_completed(run, "run_gnc_review")
            return run.gnc_review_result
        except Exception as exc:
            trace.status = "failed"
            trace.warnings.append(str(exc))
            raise
        finally:
            trace.elapsed_ms = int((time.perf_counter() - started) * 1000)
            if trace not in run.skill_traces:
                run.skill_traces.append(trace)
            if hasattr(self._host, "checkpoint_run"):
                self._host.checkpoint_run(run)

    def load_existing_gnc_result(self, review_id: str) -> dict[str, Any]:
        raw = review_id.strip()
        if not raw:
            return {}
        path = Path(raw)
        if path.is_absolute() or ".." in path.parts or len(path.parts) != 1:
            raise ValueError("GNC source_review_id 不允许使用绝对路径或路径遍历")
        root = GNC_RUNS_DIR.resolve()
        resolved = (root / f"{raw}.json").resolve()
        if root != resolved and root not in resolved.parents:
            raise ValueError("GNC source_review_id 超出 GNC_RUNS_DIR")
        if not resolved.exists() or not resolved.is_file():
            return {}
        data = json.loads(resolved.read_text(encoding="utf-8"))
        result = data.get("result") if isinstance(data, dict) else None
        if isinstance(result, dict):
            result.setdefault("gnc_review_id", raw)
            result.setdefault("review_id", raw)
            return result
        if isinstance(data, dict):
            data.setdefault("gnc_review_id", raw)
            data.setdefault("review_id", raw)
            return data
        return {}

    def gnc_materials_for_run(self, run: SuperAgentRun) -> list[dict[str, Any]]:
        if run.source_review_id and run.input_mode == SuperAgentInputMode.EXISTING_REVIEW_PLUS:
            try:
                from data_agent.review_plus.service import get_review_plus_service

                task = get_review_plus_service().get_review(run.source_review_id)
                if task:
                    return [material.model_dump(mode="json") for material in task.materials]
            except Exception as exc:
                logger.warning("[SuperAgent] Failed to load Review-Plus materials for GNC: %s", exc)
        materials = [dict(material) for material in run.structured_bundle.materials]
        if any(str(material.get("content") or "").strip() for material in materials):
            return materials
        chunk_docs = []
        for index, chunk in enumerate(run.structured_bundle.chunks, start=1):
            content = str(
                chunk.get("content")
                or chunk.get("text")
                or chunk.get("markdown")
                or chunk.get("quote")
                or ""
            ).strip()
            if not content:
                continue
            chunk_docs.append(
                {
                    "name": chunk.get("document_name") or chunk.get("source") or f"chunk-{index}",
                    "content": content,
                    "role": "subject_document",
                    "parser_type": "structured_bundle",
                }
            )
        if chunk_docs:
            return chunk_docs
        return self._gnc_materials_from_parse_artifact(run) or materials

    def _gnc_materials_from_parse_artifact(self, run: SuperAgentRun) -> list[dict[str, Any]]:
        parse_artifact = run.structured_bundle.parse_artifact or {}
        if not parse_artifact and isinstance(run.parse_preview, dict):
            parse_artifact = dict(run.parse_preview.get("parse_artifact") or {})
        if not parse_artifact:
            return []

        materials: list[dict[str, Any]] = []
        seen_names: set[str] = set()

        def _append(name: str, content: str, *, parser_type: str = "parse_artifact") -> None:
            normalized_name = name.strip() or "document"
            if not content.strip():
                return
            key = normalized_name.lower()
            if key in seen_names:
                return
            seen_names.add(key)
            materials.append(
                {
                    "name": normalized_name,
                    "content": content,
                    "role": "subject_document",
                    "parser_type": parser_type,
                }
            )

        for item in parse_artifact.get("parsed_documents") or []:
            if not isinstance(item, dict):
                continue
            document = item.get("document") if isinstance(item.get("document"), dict) else {}
            file_name = str(
                item.get("file_name")
                or document.get("file_name")
                or item.get("name")
                or "document"
            )
            blocks = document.get("blocks") or []
            from data_agent.super_agent.helpers import _block_full_content

            content = "\n\n".join(
                _block_full_content(block)
                for block in blocks
                if isinstance(block, dict) and _block_full_content(block)
            ).strip()
            if not content:
                content = str(item.get("content") or item.get("text") or item.get("markdown") or "").strip()
            _append(file_name, content, parser_type=str(item.get("parser_name") or "parse_artifact"))

        document_ir = parse_artifact.get("document_ir") or run.structured_bundle.document_ir or {}
        if isinstance(document_ir, dict):
            grouped_visual: dict[str, list[str]] = {}
            for visual in document_ir.get("visual_elements") or []:
                if not isinstance(visual, dict):
                    continue
                text = str(visual.get("description") or "").strip()
                if not text:
                    continue
                source = str(visual.get("source_file_name") or "document")
                grouped_visual.setdefault(source, []).append(text)
            for file_name, parts in grouped_visual.items():
                _append(file_name, "\n\n".join(parts), parser_type="document_ir_visual")

        layout_blocks = document_ir.get("layout_blocks") if isinstance(document_ir, dict) else []
        if isinstance(layout_blocks, list):
            grouped: dict[str, list[str]] = {}
            for block in layout_blocks:
                if not isinstance(block, dict):
                    continue
                text = str(block.get("text") or block.get("content") or "").strip()
                if not text:
                    continue
                source = str(block.get("source_file_name") or block.get("file_name") or "document")
                grouped.setdefault(source, []).append(text)
            for file_name, parts in grouped.items():
                _append(file_name, "\n\n".join(parts), parser_type="document_ir")

        evidence_pool = parse_artifact.get("evidence_pool") or run.structured_bundle.evidence_pool or {}
        for evidence in (evidence_pool.get("evidences") or []) if isinstance(evidence_pool, dict) else []:
            if not isinstance(evidence, dict):
                continue
            source_type = str(evidence.get("source_type") or "")
            excerpt = str(evidence.get("excerpt") or evidence.get("quote") or evidence.get("text") or "").strip()
            if not excerpt:
                continue
            source = str(evidence.get("source_file_name") or evidence.get("document_name") or "document")
            parser_type = "evidence_pool"
            if source_type in {"visual_description", "parse_calibration"}:
                parser_type = source_type
            _append(source, excerpt, parser_type=parser_type)

        section_tree = parse_artifact.get("section_tree") or run.structured_bundle.section_tree or {}
        for section in (section_tree.get("sections") or []) if isinstance(section_tree, dict) else []:
            if not isinstance(section, dict):
                continue
            text = str(section.get("text") or section.get("content") or "").strip()
            if not text:
                continue
            source = str(section.get("source_file_name") or section.get("title") or "document")
            _append(source, text, parser_type="section_tree")

        return materials

    def execute_gnc_workflow(self, workflow: Any, payload: dict[str, Any]) -> Any:
        for method_name in ("execute", "run", "review", "invoke"):
            method = getattr(workflow, method_name, None)
            if not callable(method):
                continue
            result = method(payload)
            if asyncio.iscoroutine(result):
                return asyncio.run(result)
            return result
        if callable(workflow):
            result = workflow(payload)
            if asyncio.iscoroutine(result):
                return asyncio.run(result)
            return result
        raise ValueError("GNC review workflow 未暴露 execute/run/review/invoke 调用入口")

    def run_gnc_design_review(self, payload: dict[str, Any], *, runner: Any = None) -> dict[str, Any]:
        from data_agent.integrations.satellite_review.gnc_schemas import GNCReviewMode, GNCReviewRequest

        if runner is None:
            from data_agent.integrations.satellite_review.gnc_workflow import run_gnc_design_review as runner

        raw_mode = str(payload.get("review_mode") or "single_doc")
        documents = []
        review_rules = []
        for material in payload.get("materials") or []:
            role = str(material.get("role") or "")
            item = {
                "name": material.get("name", ""),
                "content": material.get("content", ""),
                "file_path": material.get("file_path", ""),
                "version": material.get("document_version", ""),
                "metadata": {
                    "role": role,
                    "baseline_id": material.get("baseline_id", ""),
                    "parser_type": material.get("parser_type", ""),
                },
            }
            if role in {"review_rule", "checklist"}:
                review_rules.append(
                    {
                        "title": material.get("name", "") or "审查规则",
                        "requirement_text": material.get("content", ""),
                        "source": material.get("name", ""),
                    }
                )
            else:
                documents.append(item)
        if not documents:
            documents = [
                {
                    "name": material.get("name", ""),
                    "content": material.get("content", ""),
                    "file_path": material.get("file_path", ""),
                    "metadata": {"role": material.get("role", "")},
                }
                for material in payload.get("materials") or []
            ]
        mode = GNCReviewMode.SINGLE_DOC
        if raw_mode == "multi_doc" or (raw_mode == "full" and len(documents) > 1):
            mode = GNCReviewMode.MULTI_DOC

        raw_metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        metadata = {
            "review_id": payload.get("review_id") or payload.get("run_id") or "",
            "structured_bundle": payload.get("structured_bundle") or {},
            **raw_metadata,
        }
        if not str(metadata.get("template_id") or metadata.get("review_template_id") or "").strip():
            metadata["template_id"] = "GNC_ALL"

        request_kwargs: dict[str, Any] = {
            "name": payload.get("objective", "") or "Super Agent GNC Review",
            "documents": documents,
            "review_rules": review_rules,
            "mode": mode,
            "metadata": metadata,
        }
        if payload.get("review_phase"):
            request_kwargs["review_phase"] = payload["review_phase"]
        if payload.get("review_scope"):
            request_kwargs["review_scope"] = payload["review_scope"]
        request = GNCReviewRequest(**request_kwargs)
        result, step_outputs = runner(
            request,
            review_id=str(payload.get("review_id") or payload.get("run_id") or ""),
        )
        data = result.model_dump(mode="json")
        data["traces"] = [
            {"step": step_name, "summary": step_output}
            for step_name, step_output in step_outputs.items()
        ]
        data["review_mode"] = mode.value
        data["quality"] = data.get("quality_scores", {})
        return data
