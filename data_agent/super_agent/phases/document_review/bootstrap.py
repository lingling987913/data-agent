"""Review-Plus bootstrap for Super Agent upload flows."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, TYPE_CHECKING

from data_agent.super_agent import helpers
from data_agent.super_agent.phases.document_review.sync import ensure_review_plus_parsed
from data_agent.super_agent.schemas import (
    CreateSuperAgentRunRequest,
    SuperAgentInputMode,
    SuperAgentRun,
    SuperAgentSkillTrace,
)

if TYPE_CHECKING:
    from data_agent.super_agent.phases.base import RunHost


class BootstrapMixin:
    _host: RunHost

    def bootstrap_review_plus_task(
        self,
        run: SuperAgentRun,
        request: CreateSuperAgentRunRequest,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        existing_trace = self._host.latest_skill_trace(run, "bootstrap_review_plus_task")
        if existing_trace and existing_trace.status == "completed" and run.source_review_id:
            return dict(existing_trace.output_summary or {"review_plus_id": run.source_review_id})

        trace = SuperAgentSkillTrace(
            skill_id="bootstrap_review_plus_task",
            agent_id="data-agent:structuring_agent",
            tool_name="bootstrap_review_plus_task",
            status="running",
            input_summary={"material_count": len(request.materials)},
        )
        try:
            from data_agent.review_plus.schemas import CreateReviewPlusRequest, ReviewPlusMaterialRole
            from data_agent.review_plus.service import get_review_plus_service

            uploads: list[tuple[str, bytes]] = []
            role_by_name: dict[str, Any] = {}
            for material in request.materials:
                upload_name = (material.name or Path(material.file_path).name or "material.txt").strip()
                try:
                    raw_content = helpers._material_raw_bytes(material)
                except Exception as exc:
                    trace.warnings.append(f"材料读取失败 {upload_name}: {exc}")
                    raw_content = b""
                if not raw_content:
                    trace.warnings.append(f"材料为空: {upload_name}")
                uploads.append((upload_name, raw_content))
                role_by_name[upload_name] = material

            parser_type = next((item.parser_type for item in request.materials if item.parser_type), "auto") or "auto"
            if run.processing_mode and run.processing_mode.upper() != "OPTIMAL":
                from data_agent.agents.format_guard.mode_policy import resolve_parser_type

                first_name = request.materials[0].name or Path(request.materials[0].file_path).name
                parser_type = resolve_parser_type(first_name, run.processing_mode)
            svc = get_review_plus_service()
            task = svc.create_review(CreateReviewPlusRequest(name=run.name or request.name or "Super Agent Run"))
            task = svc.upload_materials(task.review_plus_id, uploads, parser_type=parser_type) or task

            changed_roles: list[dict[str, Any]] = []
            for material in task.materials:
                requested = role_by_name.get(material.name)
                if not requested:
                    continue
                if requested.role:
                    try:
                        role = ReviewPlusMaterialRole(requested.role)
                        material.role = role
                        material.role_confirmed = True
                        material.role_confidence = 1.0
                        material.role_reason = "Super Agent request role override"
                        changed_roles.append({"name": material.name, "role": role.value})
                    except ValueError:
                        trace.warnings.append(f"忽略不支持的材料角色: {material.name}={requested.role}")
                if requested.document_version:
                    material.document_version = requested.document_version
                if requested.baseline_id:
                    material.baseline_id = requested.baseline_id

            svc._save_task(task)
            if changed_roles:
                svc.record_event(
                    task.review_plus_id,
                    "super_agent_role_overrides_applied",
                    {"roles": changed_roles},
                )
                task = svc.recheck_gatekeeping(task.review_plus_id) or task

            run.source_review_id = task.review_plus_id
            run.input_mode = SuperAgentInputMode.EXISTING_REVIEW_PLUS
            task = ensure_review_plus_parsed(svc, task, run)
            trace.status = "completed"
            trace.output_summary = {
                "review_plus_id": task.review_plus_id,
                "material_count": len(task.materials),
                "role_overrides": changed_roles,
            }
            self._host.mark_step_completed(run, "bootstrap_review_plus_task")
            return trace.output_summary
        except Exception as exc:
            trace.status = "failed"
            trace.warnings.append(str(exc))
            raise
        finally:
            trace.elapsed_ms = int((time.perf_counter() - started) * 1000)
            run.skill_traces.append(trace)

    def reapply_bootstrap_role_overrides(self, run: SuperAgentRun) -> None:
        role_overrides: list[dict[str, Any]] = []
        for skill_trace in run.skill_traces:
            if skill_trace.skill_id == "bootstrap_review_plus_task":
                role_overrides = list(skill_trace.output_summary.get("role_overrides") or [])
        if not role_overrides or not run.source_review_id:
            return

        from data_agent.review_plus.schemas import ReviewPlusMaterialRole
        from data_agent.review_plus.service import get_review_plus_service

        svc = get_review_plus_service()
        task = svc.get_review(run.source_review_id)
        if not task:
            return
        role_by_name = {item.get("name"): item.get("role") for item in role_overrides}
        changed = False
        for material in task.materials:
            role = role_by_name.get(material.name)
            if not role:
                continue
            material.role = ReviewPlusMaterialRole(role)
            material.role_confirmed = True
            material.role_confidence = 1.0
            material.role_reason = "Super Agent request role override"
            changed = True
        if changed:
            svc._save_task(task)
            svc.record_event(
                task.review_plus_id,
                "super_agent_role_overrides_reapplied",
                {"roles": role_overrides},
            )
