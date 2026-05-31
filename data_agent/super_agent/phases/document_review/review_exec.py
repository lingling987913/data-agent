"""Review execution orchestration for document_review phase."""

from __future__ import annotations

import time
from typing import Any, TYPE_CHECKING

from data_agent.super_agent import helpers
from data_agent.super_agent.phases.base import advance_wizard_phase
from data_agent.super_agent.execution_plan import resolve_parsing_plan, skills_for_execution
from data_agent.super_agent.phases.base import PhaseHandlerBase
from data_agent.super_agent.phases.document_review.bootstrap import BootstrapMixin
from data_agent.super_agent.phases.document_review.gnc import GncMixin
from data_agent.super_agent.phases.document_review.structure import StructureMixin
from data_agent.super_agent.phases.document_review.sync import (
    ensure_review_plus_parsed,
    sync_structured_bundle_to_review_plus_task,
    sync_wizard_parse_artifact_to_review_plus_task,
)
from data_agent.super_agent.phases.document_review.smart_orchestrator import (
    SmartReviewPlan,
    committee_corpus_text_for_run,
    committee_materials_for_run,
    record_smart_degradation,
    resolve_smart_review_plan,
    _structure_context_for_run,
)
from data_agent.super_agent.schemas import (
    CreateSuperAgentRunRequest,
    SuperAgentReviewMode,
    SuperAgentRoute,
    SuperAgentRouteDecision,
    SuperAgentRun,
    SuperAgentSkillTrace,
)

if TYPE_CHECKING:
    from data_agent.super_agent.execution_plan import ParsingPlan


class ReviewExecMixin:
    def execute_pipeline(self, ctx) -> None:
        run = ctx.run
        self.execute_skills(
            run,
            ctx.decision,
            request=ctx.request,
            plan=ctx.plan,
            resume=ctx.resume,
        )
        advance_wizard_phase(run, "document_review", status="completed")
        self._host.checkpoint_run(run)

    def execute_skills(
        self,
        run: SuperAgentRun,
        decision: SuperAgentRouteDecision,
        *,
        request: CreateSuperAgentRunRequest | None = None,
        plan: ParsingPlan | None = None,
        resume: bool = False,
        force_rerun: bool = False,
    ) -> None:
        """L4: dispatch review-plus / gnc / structure skills by route."""
        route = decision.route
        skills = skills_for_execution(run, decision, plan=plan)
        already_structured = self._host.structure_phase_complete(run)

        def _should_run_skill(skill_id: str) -> bool:
            return not resume or not self._host.step_completed(run, skill_id)

        needs_post_bootstrap_classify = bool(
            route != SuperAgentRoute.SMART
            and (
                (plan and plan.bootstrap_review_plus)
                or (
                    resume
                    and self._host.step_completed(run, "bootstrap_review_plus_task")
                    and not self._host.step_completed(run, "classify_post_bootstrap")
                )
            )
        )
        if needs_post_bootstrap_classify and resume:
            if not self._host.step_completed(run, "classify_post_bootstrap"):
                post_decision = self._host.classify_task(run, request=request)
                run.route_decision = post_decision
                if post_decision.classification:
                    run.classification = post_decision.classification
                self._host.mark_step_completed(run, "classify_post_bootstrap")
            route = SuperAgentRoute.REVIEW_PLUS
            skills = ["run_review_plus"]

        if (
            plan
            and plan.reuse_review_plus_parse
            and not already_structured
            and _should_run_skill("structure_materials")
        ):
            self._host.structure_materials(run, request=request)
            already_structured = self._host.structure_phase_complete(run)

        if plan and plan.bootstrap_review_plus and not resume and route != SuperAgentRoute.SMART:
            decision = self._host.classify_task(run, request=request)
            run.route_decision = decision
            if decision.classification:
                run.classification = decision.classification
            self._host.mark_step_completed(run, "classify_post_bootstrap")
            route = SuperAgentRoute.REVIEW_PLUS
            skills = ["run_review_plus"]

        if route == SuperAgentRoute.SMART:
            smart_plan = resolve_smart_review_plan(run, decision, force_refresh=force_rerun)
            record_smart_degradation(run, smart_plan)
            if plan is None:
                plan = resolve_parsing_plan(run, decision, request=request)
            if smart_plan.bootstrap_review_plus and not run.source_review_id:
                bootstrap_request = request
                if bootstrap_request is None and hasattr(self._host, "build_execution_request"):
                    bootstrap_request = self._host.build_execution_request(run)
                if bootstrap_request and _should_run_skill("bootstrap_review_plus_task"):
                    self.bootstrap_review_plus_task(run, bootstrap_request)
            self._execute_smart_review_plan(
                run,
                smart_plan,
                request=request,
                already_structured=already_structured,
                should_run_skill=_should_run_skill,
                force_rerun=force_rerun,
            )
            return

        for skill_id in skills:
            if not _should_run_skill(skill_id):
                continue
            if skill_id == "run_review_plus":
                self._host.run_review_plus(
                    run,
                    skip_structure=already_structured,
                    force_rerun=force_rerun,
                )
            elif skill_id == "run_gnc_review":
                self._host.run_gnc_review(run, request=request, allow_missing=True)
            elif skill_id == "structure_materials" and not already_structured:
                self._host.structure_materials(run, request=request)

        if route == SuperAgentRoute.HYBRID and not run.gnc_review_result and _should_run_skill("run_gnc_review"):
            self._host.run_gnc_review(run, request=request, allow_missing=True)

    def _execute_smart_review_plan(
        self,
        run: SuperAgentRun,
        smart_plan: SmartReviewPlan,
        *,
        request: CreateSuperAgentRunRequest | None,
        already_structured: bool,
        should_run_skill,
        force_rerun: bool = False,
    ) -> None:
        if smart_plan.primary_path == "structure_only":
            if not already_structured and should_run_skill("structure_materials"):
                self._host.structure_materials(run, request=request)
            return

        if not already_structured and should_run_skill("structure_materials"):
            self._host.structure_materials(run, request=request)

        if smart_plan.primary_path == "gnc":
            if should_run_skill("run_gnc_review"):
                self._host.run_gnc_review(run, request=request, allow_missing=True)
            return

        if smart_plan.primary_path == "review_plus":
            if should_run_skill("run_review_plus"):
                self._host.run_review_plus(run, skip_structure=True, force_rerun=force_rerun)
            return

        if should_run_skill("smart_review_committee"):
            self.run_smart_committee_review(run, smart_plan, request=request)

    def _load_smart_task_board(self, run: SuperAgentRun) -> dict[str, Any] | None:
        classification = run.classification if isinstance(run.classification, dict) else {}
        stored = classification.get("smart_task_board")
        if isinstance(stored, dict):
            return stored
        doc_review = run.phase_artifacts.get("document_review")
        if isinstance(doc_review, dict):
            artifact_board = doc_review.get("smart_task_board")
            if isinstance(artifact_board, dict):
                return artifact_board
        from data_agent.core.task_board_store import load_task_board

        file_board = load_task_board(run.run_id)
        if isinstance(file_board, dict):
            return file_board
        return None

    def _persist_smart_task_board(self, run: SuperAgentRun, board_payload: dict[str, Any]) -> None:
        from data_agent.core.task_board import TaskBoard, smart_task_board_summary
        from data_agent.core.task_board_store import save_task_board

        board = TaskBoard.from_dict(board_payload)
        summary = smart_task_board_summary(board) if board else {}
        if not isinstance(run.classification, dict):
            run.classification = {}
        run.classification["smart_task_board"] = board_payload
        run.classification["smart_task_board_summary"] = summary
        doc_review = run.phase_artifacts.get("document_review")
        if not isinstance(doc_review, dict):
            doc_review = {}
        run.phase_artifacts["document_review"] = {
            **doc_review,
            "smart_task_board": board_payload,
            "smart_task_board_summary": summary,
        }
        save_task_board(run.run_id, board_payload, summary=summary)
        if hasattr(self._host, "checkpoint_run"):
            self._host.checkpoint_run(run)

    @staticmethod
    def _aggregate_committee_quality(specialist_reviews: list[dict[str, Any]], board_summary: dict[str, Any]) -> dict[str, Any]:
        from data_agent.core.task_board import aggregate_smart_committee_quality

        return aggregate_smart_committee_quality(specialist_reviews, board_summary)

    def run_smart_committee_review(
        self,
        run: SuperAgentRun,
        smart_plan: SmartReviewPlan,
        *,
        request: CreateSuperAgentRunRequest | None = None,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        trace = SuperAgentSkillTrace(
            skill_id="smart_review_committee",
            agent_id="data-agent:smart_review_orchestrator",
            tool_name="run_smart_review_committee",
            status="running",
            input_summary={
                "primary_path": smart_plan.primary_path,
                "specialist_ids": list(smart_plan.specialist_ids),
                "force_refresh": force_refresh,
            },
        )
        run.skill_traces.append(trace)
        try:
            from data_agent.core.sub_agent_runner import SubAgentRunner
            from data_agent.core.task_board import (
                build_smart_committee_task_board,
                smart_task_board_summary,
                task_board_to_dict,
            )

            if not self._host.structure_phase_complete(run):
                self._host.structure_materials(run, request=request)

            classification = dict(run.classification) if isinstance(run.classification, dict) else {}
            materials = committee_materials_for_run(run, classification)
            corpus_text = committee_corpus_text_for_run(run, classification, materials)
            has_material_text = any(str(item.get("content") or "").strip() for item in materials)
            if not corpus_text.strip() and not has_material_text:
                blocked_message = "解析/结构化未产出可审查正文或证据，无法执行 SMART 委员会审查。"
                trace.status = "blocked"
                trace.warnings.append(blocked_message)
                trace.output_summary = {
                    "status": "blocked",
                    "message": blocked_message,
                    "degradation_summary": list(smart_plan.degradation_summary),
                }
                run.review_plus_result = {
                    "status": "blocked",
                    "review_mode": "smart_committee",
                    "message": blocked_message,
                }
                record_smart_degradation(run, smart_plan)
                return run.review_plus_result

            chief_plan = smart_plan.chief_review_plan
            if not isinstance(chief_plan, dict) or not chief_plan.get("selected_agents"):
                raise ValueError("缺少持久化的 chief_review_plan，请先完成 SMART 计划预览/调度。")

            section_tree, evidence_pool = _structure_context_for_run(run)
            from data_agent.core.domain_registry import resolve_domain_id
            from data_agent.super_agent.phases.document_review.smart_bootstrap import (
                synthesize_minimal_review_context,
            )

            domain_id = resolve_domain_id(classification)
            bootstrap_payload = synthesize_minimal_review_context(run, run.objective or "")
            bootstrap_summary = dict(bootstrap_payload.get("bootstrap_summary") or {})
            evidence_summary = {
                "corpus_chars": len(corpus_text),
                "material_count": len(materials),
                "section_count": len((section_tree or {}).get("sections") or []),
                "evidence_count": len((evidence_pool or {}).get("evidences") or []),
                "bootstrap_mode": bootstrap_payload.get("bootstrap_mode", ""),
                "synthetic_check_item_count": bootstrap_summary.get("synthetic_check_item_count", 0),
                "source_evidence_ref_count": bootstrap_summary.get("source_evidence_ref_count", 0),
            }

            existing_board = None if force_refresh else self._load_smart_task_board(run)
            task_specs = list(smart_plan.task_specs) if smart_plan.task_specs else None
            if task_specs:
                from data_agent.core.task_board import build_task_board_from_specs

                task_board = build_task_board_from_specs(
                    task_specs,
                    evidence_summary,
                    existing_board,
                    force_refresh=force_refresh,
                )
            else:
                task_board = build_smart_committee_task_board(
                    chief_plan,
                    evidence_summary,
                    existing_board,
                    specialist_ids=list(smart_plan.specialist_ids),
                    force_refresh=force_refresh,
                    bootstrap_summary=bootstrap_summary,
                    domain_id=domain_id,
                )

            runner = SubAgentRunner()
            context = {
                "materials": materials,
                "corpus_text": corpus_text,
                "section_tree": section_tree,
                "evidence_pool": evidence_pool,
                "objective": run.objective or "",
                "chief_plan": chief_plan,
                "domain_id": domain_id,
                "bootstrap_mode": bootstrap_payload.get("bootstrap_mode", ""),
                "synthetic_check_items": bootstrap_payload.get("synthetic_check_items") or [],
                "synthetic_task_book": bootstrap_payload.get("synthetic_task_book") or "",
                "source_evidence_refs": bootstrap_payload.get("source_evidence_refs") or [],
                "check_items": bootstrap_payload.get("synthetic_check_items") or [],
                "bootstrap_summary": bootstrap_summary,
                "task_board": task_board,
            }

            from data_agent.core.task_scheduler import run_task_board

            def _task_runner(board_task):
                return runner.run_specialist_task(board_task, context)

            def _checkpoint(board_obj, task_item, phase: str) -> None:
                if phase == "after" or phase == "batch_end":
                    self._persist_smart_task_board(run, task_board_to_dict(board_obj))

            scheduler_result = run_task_board(
                task_board,
                _task_runner,
                context,
                checkpoint=_checkpoint,
            )
            task_board = scheduler_result.board
            board_summary = scheduler_result.summary

            from data_agent.core.task_board import specialist_reviews_from_task_board

            specialist_reviews = specialist_reviews_from_task_board(task_board)

            board_payload = task_board_to_dict(task_board)
            self._persist_smart_task_board(run, board_payload)

            specialist_ids = list(smart_plan.specialist_ids) or [
                str(item.get("agent_id") or "")
                for item in chief_plan.get("selected_agents") or []
                if item.get("agent_id")
            ]
            finding_count = sum(len(item.get("findings") or []) for item in specialist_reviews)
            quality_meta = self._aggregate_committee_quality(specialist_reviews, board_summary)
            overall_status = "completed"
            if board_summary.get("failed"):
                overall_status = "failed"
            elif board_summary.get("blocked"):
                overall_status = "blocked"
            elif quality_meta.get("limited"):
                overall_status = "limited"

            all_tasks_terminal = all(
                task.status in {"completed", "failed", "blocked", "skipped"}
                for task in task_board.tasks
            )
            all_tasks_completed = (
                task_board.tasks
                and all(task.status == "completed" for task in task_board.tasks)
            )

            run.review_plus_result = {
                "status": overall_status,
                "review_mode": "smart_committee",
                "chief_review_plan": chief_plan,
                "specialist_reviews": specialist_reviews,
                "specialist_ids": specialist_ids,
                "smart_task_board": board_payload,
                "task_board_summary": board_summary,
                "scheduler_summary": board_summary,
                "arbiter_summary": scheduler_result.arbiter_summary,
                "replan_suggestions": list(scheduler_result.replan_suggestions),
                "followup_task_specs": list(scheduler_result.followup_task_specs),
                "bootstrap_summary": bootstrap_summary,
                "domain_id": domain_id,
                "total_tasks": board_summary.get("task_count", 0),
                "completed_tasks": board_summary.get("completed", 0),
                "failed_tasks": board_summary.get("failed", 0),
                "blocked_tasks": board_summary.get("blocked", 0),
                "skipped_tasks": board_summary.get("skipped", 0),
                "limited_tasks": board_summary.get("limited", 0),
                "finding_count": finding_count,
                "execution_mode_summary": quality_meta["execution_mode_summary"],
                "citation_coverage": quality_meta["citation_coverage"],
                "evidence_coverage": quality_meta["evidence_coverage"],
                "citation_coverage_source": quality_meta.get("citation_coverage_source"),
                "limited": quality_meta["limited"],
                "limited_review_count": quality_meta.get("limited_review_count", 0),
            }
            from data_agent.core.task_board import enrich_smart_committee_result

            run.review_plus_result = enrich_smart_committee_result(
                run.review_plus_result,
                classification=classification,
                phase_artifacts=run.phase_artifacts if isinstance(run.phase_artifacts, dict) else {},
            )
            doc_review = run.phase_artifacts.get("document_review")
            if not isinstance(doc_review, dict):
                doc_review = {}
            run.phase_artifacts["document_review"] = {
                **doc_review,
                "smart_committee_result": dict(run.review_plus_result),
                "smart_task_board": board_payload,
                "smart_task_board_summary": board_summary,
                "bootstrap_summary": bootstrap_summary,
            }
            run.classification["bootstrap_summary"] = bootstrap_summary

            trace.status = "completed" if overall_status in {"completed", "limited"} else overall_status
            trace.output_summary = {
                "execution_model": "task_board_subagents",
                "specialist_count": len(specialist_ids),
                "total_tasks": board_summary.get("task_count", 0),
                "completed_tasks": board_summary.get("completed", 0),
                "failed_tasks": board_summary.get("failed", 0),
                "blocked_tasks": board_summary.get("blocked", 0),
                "skipped_tasks": board_summary.get("skipped", 0),
                "limited_tasks": board_summary.get("limited", 0),
                "finding_count": finding_count,
                "corpus_chars": evidence_summary["corpus_chars"],
                "material_count": evidence_summary["material_count"],
                "section_count": evidence_summary["section_count"],
                "evidence_count": evidence_summary["evidence_count"],
                "bootstrap_summary": bootstrap_summary,
                "degradation_summary": list(smart_plan.degradation_summary),
                "execution_mode_summary": quality_meta["execution_mode_summary"],
                "citation_coverage": quality_meta["citation_coverage"],
                "limited": quality_meta["limited"],
                "has_arbiter_summary": bool(scheduler_result.arbiter_summary),
                "replan_suggestions": list(scheduler_result.replan_suggestions),
            }
            record_smart_degradation(run, smart_plan)
            if quality_meta.get("limited"):
                from data_agent.super_agent.smart_diagnostics import format_committee_limited_note

                limited_note = format_committee_limited_note()
                if limited_note not in run.trace_report.degradation_summary:
                    run.trace_report.degradation_summary.append(limited_note)
            if all_tasks_completed and overall_status in {"completed", "limited"}:
                self._host.mark_step_completed(run, "smart_review_committee")
            elif all_tasks_terminal and overall_status == "failed":
                pass
            if hasattr(self._host, "checkpoint_run"):
                self._host.checkpoint_run(run)
            return run.review_plus_result
        except Exception as exc:
            trace.status = "failed"
            trace.warnings.append(str(exc))
            raise
        finally:
            trace.elapsed_ms = int((time.perf_counter() - started) * 1000)

    def run_review_plus(
        self,
        run: SuperAgentRun,
        *,
        skip_structure: bool = False,
        force_rerun: bool = False,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        existing_trace = self._host.latest_skill_trace(run, "run_review_plus")
        review_result = run.review_plus_result or {}
        if (
            not force_rerun
            and existing_trace
            and existing_trace.status == "completed"
            and review_result.get("status") == "completed"
            and review_result.get("review_plus_id") == run.source_review_id
        ):
            return review_result

        if existing_trace and existing_trace.status == "running":
            trace = existing_trace
        else:
            trace = SuperAgentSkillTrace(
                skill_id="run_review_plus",
                agent_id="data-agent:review_plus_execution_agent",
                tool_name="run_review_plus",
                status="running",
                input_summary={"review_plus_id": run.source_review_id},
            )
            run.skill_traces.append(trace)
            self._host.checkpoint_run(run)
        try:
            from data_agent.review_plus.service import get_review_plus_service

            svc = get_review_plus_service()
            task = svc.get_review(run.source_review_id)
            if not task:
                raise ValueError(f"Review-Plus task not found: {run.source_review_id}")
            sync_structured_bundle_to_review_plus_task(svc, task, run)
            workflow_error = ""
            if force_rerun and task.status == "completed":
                svc.invalidate_review_execution_results(run.source_review_id)
                task = svc.get_review(run.source_review_id) or task
            if task.status != "completed":
                if task.status in {"draft", "materials_uploaded", "classified", "blocked", "limited_pass"}:
                    try:
                        svc.start_review(run.source_review_id)
                    except Exception as exc:
                        workflow_error = str(exc)
                        trace.warnings.append(f"Review-Plus 准入降级: {workflow_error}")
                if not workflow_error:
                    try:
                        task = self._host.run_with_periodic_checkpoints(
                            run,
                            lambda: svc.continue_started_review(run.source_review_id) or task,
                        )
                    except Exception as exc:
                        workflow_error = str(exc)
                        trace.warnings.append(f"Review-Plus workflow 降级: {workflow_error}")
                        task = svc.get_review(run.source_review_id) or task
                self.reapply_bootstrap_role_overrides(run)
                task = svc.get_review(run.source_review_id) or task
            if not skip_structure and task.status != "completed":
                self._host.structure_materials(run)
            elif (
                not run.structured_bundle.materials
                and run.source_review_id
                and task.status != "completed"
            ):
                self._host.structure_materials(run)
            task = svc.get_review(run.source_review_id) or task
            report = task.report.model_dump(mode="json") if task.report else None
            run.review_plus_result = {
                "review_plus_id": task.review_plus_id,
                "status": task.status,
                "finding_count": len(task.findings),
                "cross_document_item_count": len(task.cross_document_review_items or []),
                "findings": [finding.model_dump(mode="json") for finding in task.findings],
                "cross_doc_findings": list(task.cross_document_review_items or []),
                "coverage_matrix": task.coverage_matrix,
                "traceability_summary": (task.traceability_result or {}).get("summary", {}),
                "review_conclusion": (report or {}).get("conclusion", ""),
                "report": report,
                "specialist_reviews": list(task.specialist_reviews or []),
                "document_format_review": dict(task.document_format_review or {}),
                "chief_review_plan": dict(task.chief_review_plan or {}),
            }
            trace.status = "failed" if workflow_error else "completed"
            trace.output_summary = {
                "status": task.status,
                "finding_count": len(task.findings),
                "cross_document_item_count": len(task.cross_document_review_items or []),
                "workflow_error": workflow_error,
            }
            if trace.status == "completed":
                self._host.mark_step_completed(run, "run_review_plus")
        except Exception as exc:
            trace.status = "failed"
            trace.warnings.append(str(exc))
            raise
        finally:
            trace.elapsed_ms = int((time.perf_counter() - started) * 1000)
        return run.review_plus_result

    def sync_wizard_parse_artifact_to_review_plus_task(self, svc: Any, task: Any, run: SuperAgentRun) -> None:
        sync_wizard_parse_artifact_to_review_plus_task(svc, task, run)

    def sync_structured_bundle_to_review_plus_task(self, svc: Any, task: Any, run: SuperAgentRun) -> None:
        sync_structured_bundle_to_review_plus_task(svc, task, run)

    def execute_review_for_run(
        self,
        run_id: str,
        *,
        request: CreateSuperAgentRunRequest | None = None,
        skip_reparse: bool = True,
        force_rerun: bool = False,
    ) -> dict[str, Any]:
        """Independent review API: execute review skills using existing parse artifact."""
        from data_agent.parsing.artifact_builder import is_parse_artifact_complete

        run = self._host.get_run(run_id)
        if not run:
            raise ValueError(f"Super Agent run not found: {run_id}")

        parse_artifact = dict(run.structured_bundle.parse_artifact or {})
        if not parse_artifact and isinstance(run.parse_preview, dict):
            parse_artifact = dict(run.parse_preview.get("parse_artifact") or {})
        if not is_parse_artifact_complete(parse_artifact):
            raise ValueError("请先完成文档解析（parse artifact 不完整或缺失）")

        if request is None:
            request = self._host.build_execution_request(run)

        from data_agent.super_agent.post_parse_router import ensure_post_parse_route_decision

        ensure_post_parse_route_decision(run)
        decision = run.route_decision
        if not decision:
            decision = self._host.classify_task(run, request=request)
            run.route_decision = decision
            if decision.classification:
                run.classification = decision.classification

        plan = resolve_parsing_plan(run, decision, request=request)

        if plan.bootstrap_review_plus and not run.source_review_id:
            self.bootstrap_review_plus_task(run, request)
        elif run.source_review_id:
            from data_agent.review_plus.service import get_review_plus_service

            svc = get_review_plus_service()
            task = svc.get_review(run.source_review_id)
            if task:
                ensure_review_plus_parsed(svc, task, run)

        self.execute_skills(
            run,
            decision,
            request=request,
            plan=plan,
            resume=skip_reparse,
            force_rerun=force_rerun,
        )

        advance_wizard_phase(run, "document_review", status="completed")
        self._host.checkpoint_run(run)

        route = decision.route.value if decision else ""
        return {
            "run_id": run.run_id,
            "route": route,
            "review_plus_result": dict(run.review_plus_result or {}),
            "gnc_review_result": dict(run.gnc_review_result or {}),
            "structured_bundle": run.structured_bundle,
            "skill_traces": list(run.skill_traces),
        }


class DocumentReviewPhaseHandler(
    ReviewExecMixin,
    BootstrapMixin,
    StructureMixin,
    GncMixin,
    PhaseHandlerBase,
):
    phase_id = "document_review"
    wizard_step = 4

    def __init__(self, host):
        super().__init__(host)
