"""Review Data Super Agent facade service.

Thin orchestration over Review-Plus (and future GNC). Phase handlers live in
``data_agent.super_agent.phases``; this module provides RunHost infrastructure
and delegates wizard / pipeline work to phase registries.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

from data_agent.core.agent_debug_log import agent_debug_log
from data_agent.core.config import RUNS_DIR, SUPER_AGENT_RUNS_DIR, SUPER_AGENT_UPLOAD_DIR
from data_agent.review_plus.task_artifact_cleanup import remove_task_artifacts
from data_agent.super_agent import helpers
from data_agent.super_agent.run_paths import (
    canonical_run_json_path,
    iter_run_json_paths,
    legacy_run_json_path,
    resolve_run_json_path,
    run_dir,
)
from data_agent.super_agent.execution_plan import ParsingPlan
from data_agent.super_agent.phases import (
    PhaseContext,
    PhaseRegistry,
    build_phase_registry,
)
from data_agent.super_agent.wizard_invalidate import (
    invalidate_wizard_from_phase,
    materials_changed,
)
from data_agent.super_agent.schemas import (
    CreateSuperAgentRunRequest,
    StructuredReviewBundle,
    SuperAgentCapabilities,
    SuperAgentInputMode,
    SuperAgentMaterial,
    SuperAgentParseRunRequest,
    SuperAgentParseRunResponse,
    SuperAgentQualityReport,
    SuperAgentReviewRunRequest,
    SuperAgentReviewRunResponse,
    SuperAgentRoute,
    SuperAgentRouteDecision,
    SuperAgentRun,
    SuperAgentSkillTrace,
    SuperAgentStatus,
    SuperAgentTraceReport,
    SaveWizardCheckpointRequest,
)

logger = logging.getLogger(__name__)

# running 且无 checkpoint 超过此秒数，视为 stale（worker 可能已退出但未改状态）
STALE_RUNNING_SECONDS = 120

# 重跑审查时需清掉的 Super Agent 步骤/skill，保留 parse/structure/bootstrap 结果。
REVIEW_EXECUTION_SKILL_IDS = frozenset(
    {"run_review_plus", "run_gnc_review", "smart_review_committee"}
)
# Review-Plus 等长步骤可能 30+ 分钟无 checkpoint，单独放宽 stale 阈值
LONG_RUNNING_SKILL_STALE_SECONDS: dict[str, float] = {
    "run_review_plus": 45 * 60,
    "run_gnc_review": 45 * 60,
    "bootstrap_review_plus_task": 15 * 60,
    "structure_materials": 10 * 60,
}
DOCUMENT_REVIEW_ROUTES = frozenset(
    {
        SuperAgentRoute.REVIEW_PLUS,
        SuperAgentRoute.GNC_REVIEW,
        SuperAgentRoute.GNC_REVIEW_ONLY,
        SuperAgentRoute.HYBRID,
        SuperAgentRoute.SMART,
    }
)

enrich_material_previews = helpers.enrich_material_previews
_preview_processing_mode_for_tier = helpers._preview_processing_mode_for_tier


MANUAL_INTERRUPT_ERROR = "用户手动中断，可继续审查恢复"


class RunInterruptedError(RuntimeError):
    """Raised when a run receives a manual interrupt request during execution."""

    def __init__(self, run_id: str):
        super().__init__(f"Super Agent run interrupted: {run_id}")
        self.run_id = run_id


class SuperAgentService:
    _instance: Optional["SuperAgentService"] = None
    _DATA_DIR = SUPER_AGENT_RUNS_DIR
    _lock = threading.RLock()

    def __new__(cls) -> "SuperAgentService":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._store = {}
            cls._instance._interrupt_requested = set()
            cls._instance._phases = build_phase_registry(cls._instance)
        return cls._instance

    @property
    def phases(self) -> PhaseRegistry:
        return self._phases

    # ------------------------------------------------------------------
    # RunHost infrastructure
    # ------------------------------------------------------------------

    def _save_run(self, run: SuperAgentRun) -> None:
        self._DATA_DIR.mkdir(parents=True, exist_ok=True)
        path = canonical_run_json_path(self._DATA_DIR, run.run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = run.model_dump_json(indent=2)
        with self._lock:
            self._store[run.run_id] = run
        path.write_text(payload, encoding="utf-8")
        legacy = legacy_run_json_path(self._DATA_DIR, run.run_id)
        if legacy.is_file():
            legacy.unlink(missing_ok=True)

    def _load_run_from_disk(self, run_id: str) -> Optional[SuperAgentRun]:
        path = resolve_run_json_path(self._DATA_DIR, run_id)
        if path is None:
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            run = SuperAgentRun.model_validate(data)
        except Exception as exc:
            logger.warning("[SuperAgent] Failed to load run from %s: %s", path.name, exc)
            return None
        if run.status == SuperAgentStatus.RUNNING:
            run.status = SuperAgentStatus.INTERRUPTED
            if not run.error:
                run.error = "服务重启导致执行中断，可自动续跑"
            run.updated_at = helpers._now()
            self._save_run(run)
            logger.info("[SuperAgent] Recovered stale running run %s -> interrupted", run.run_id)
        with self._lock:
            self._store[run.run_id] = run
        return run

    def _load_all_runs(self) -> None:
        if not self._DATA_DIR.exists():
            return
        for run_id, _path in iter_run_json_paths(self._DATA_DIR):
            if run_id in self._store:
                continue
            self._load_run_from_disk(run_id)

    def checkpoint_run(self, run: SuperAgentRun) -> None:
        """Persist intermediate run state for polling clients during long executions."""
        run.updated_at = helpers._now()
        self._save_run(run)

    def run_with_periodic_checkpoints(
        self,
        run: SuperAgentRun,
        task_fn: Callable[[], Any],
        *,
        interval_seconds: float = 60,
    ) -> Any:
        """Run a blocking task in a worker thread and checkpoint run state periodically."""
        done = threading.Event()
        result_holder: list[Any] = []
        error_holder: list[BaseException] = []

        def _worker() -> None:
            try:
                result_holder.append(task_fn())
            except BaseException as exc:
                error_holder.append(exc)
            finally:
                done.set()

        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()
        while not done.wait(timeout=interval_seconds):
            self.checkpoint_run(run)
        self.checkpoint_run(run)
        if error_holder:
            raise error_holder[0]
        return result_holder[0] if result_holder else None

    def latest_skill_trace(self, run: SuperAgentRun, skill_id: str) -> SuperAgentSkillTrace | None:
        matches = [trace for trace in run.skill_traces if trace.skill_id == skill_id]
        return matches[-1] if matches else None

    def step_completed(self, run: SuperAgentRun, step_id: str) -> bool:
        if step_id in run.completed_steps:
            return True
        trace = self.latest_skill_trace(run, step_id)
        return trace is not None and trace.status == "completed"

    def mark_step_completed(self, run: SuperAgentRun, step_id: str) -> None:
        if step_id not in run.completed_steps:
            run.completed_steps.append(step_id)
        self.checkpoint_run(run)

    def structure_phase_complete(self, run: SuperAgentRun) -> bool:
        from data_agent.parsing.artifact_builder import is_structure_artifact_complete

        if not self.step_completed(run, "structure_materials"):
            return False
        return is_structure_artifact_complete(
            run.structured_bundle.section_tree,
            run.structured_bundle.evidence_pool,
            document_ir=run.structured_bundle.document_ir,
            parse_artifact=run.structured_bundle.parse_artifact,
        )

    def parse_phase_complete(self, run: SuperAgentRun, plan: ParsingPlan) -> bool:
        from data_agent.parsing.artifact_builder import is_parse_artifact_complete

        if plan.bootstrap_review_plus:
            if not self.step_completed(run, "bootstrap_review_plus_task"):
                return False
            if run.source_review_id:
                from data_agent.review_plus.service import get_review_plus_service

                task = get_review_plus_service().get_review(run.source_review_id)
                if task:
                    return is_parse_artifact_complete(getattr(task, "parse_artifact", {}) or {})
            return False
        needs_structure = plan.run_structure_parse or plan.reuse_review_plus_parse
        if needs_structure:
            if not self.step_completed(run, "structure_materials"):
                return False
            from data_agent.parsing.artifact_builder import is_structure_artifact_complete

            return is_structure_artifact_complete(
                run.structured_bundle.section_tree,
                run.structured_bundle.evidence_pool,
                document_ir=run.structured_bundle.document_ir,
                parse_artifact=run.structured_bundle.parse_artifact,
            )
        return True

    def _is_run_stale(
        self,
        run: SuperAgentRun,
        *,
        threshold_seconds: float = STALE_RUNNING_SECONDS,
    ) -> bool:
        if run.status != SuperAgentStatus.RUNNING:
            return False
        if self._is_document_review_execution_window(run):
            return False
        threshold = threshold_seconds
        if run.skill_traces:
            last_trace = run.skill_traces[-1]
            if last_trace.status == "running":
                threshold = LONG_RUNNING_SKILL_STALE_SECONDS.get(last_trace.skill_id, threshold)
        updated = helpers._parse_iso_timestamp(run.updated_at)
        if updated is None:
            return False
        return (datetime.now() - updated).total_seconds() >= threshold

    def _is_document_review_execution_window(self, run: SuperAgentRun) -> bool:
        """Review execution can legitimately run for a long time without visible progress."""
        if run.skill_traces:
            last_trace = run.skill_traces[-1]
            if last_trace.status == "running" and last_trace.skill_id in REVIEW_EXECUTION_SKILL_IDS:
                return True
        if run.current_phase == "document_review":
            return True
        route = run.route_decision.route if run.route_decision else run.requested_route
        if route not in DOCUMENT_REVIEW_ROUTES:
            return False
        if run.review_plus_result or run.gnc_review_result:
            return False
        return run.current_phase == "document_parse" and "structure_materials" in run.completed_steps

    def _interrupt_if_stale_running(self, run: SuperAgentRun) -> SuperAgentRun:
        """Mark long-idle running runs as interrupted so clients can resume."""
        if not self._is_run_stale(run):
            return run
        run.status = SuperAgentStatus.INTERRUPTED
        if not run.error:
            run.error = "执行进度长时间未更新，可继续执行以恢复"
        run.updated_at = helpers._now()
        self._save_run(run)
        logger.info("[SuperAgent] Marked stale running run %s -> interrupted", run.run_id)
        return run

    def _raise_if_interrupt_requested(self, run_id: str) -> None:
        with self._lock:
            if run_id in self._interrupt_requested:
                raise RunInterruptedError(run_id)
        run = self.get_run(run_id)
        if run and run.status == SuperAgentStatus.INTERRUPTED:
            raise RunInterruptedError(run_id)

    def interrupt_run(self, run_id: str) -> SuperAgentRun:
        run = self.get_run(run_id)
        if not run:
            raise ValueError(f"Super Agent run not found: {run_id}")
        if run.status != SuperAgentStatus.RUNNING:
            raise ValueError(
                f"Super Agent run is not running: {run_id} (status={run.status.value})"
            )
        with self._lock:
            self._interrupt_requested.add(run_id)
        run.status = SuperAgentStatus.INTERRUPTED
        run.error = MANUAL_INTERRUPT_ERROR
        self.checkpoint_run(run)
        logger.info("[SuperAgent] Manual interrupt requested for run %s", run_id)
        return run

    # Underscore aliases kept for backward compatibility with tests and phase handlers.
    _checkpoint_run = checkpoint_run
    _run_with_periodic_checkpoints = run_with_periodic_checkpoints
    _latest_skill_trace = latest_skill_trace
    _step_completed = step_completed
    _mark_step_completed = mark_step_completed
    _structure_phase_complete = structure_phase_complete
    _parse_phase_complete = parse_phase_complete

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def build_execution_request(self, run: SuperAgentRun) -> CreateSuperAgentRunRequest:
        return CreateSuperAgentRunRequest(
            name=run.name,
            objective=run.objective,
            processing_mode=run.processing_mode,
            input_mode=run.input_mode,
            source_review_id=run.source_review_id,
            requested_route=run.requested_route,
            review_mode=run.review_mode,
            materials=run.materials,
            execute=True,
        )

    def create_run(self, req: CreateSuperAgentRunRequest) -> SuperAgentRun:
        run = SuperAgentRun(
            name=(req.name or "").strip() or "Super Agent Run",
            objective=req.objective,
            processing_mode=req.processing_mode or "OPTIMAL",
            input_mode=req.input_mode,
            source_review_id=req.source_review_id,
            requested_route=req.requested_route,
            review_mode=req.review_mode,
            materials=req.materials,
        )
        if req.classification:
            run.classification = dict(req.classification)
        with self._lock:
            self._store[run.run_id] = run
        self._save_run(run)
        if req.execute:
            return self.execute_run(run.run_id, request=req)
        return run

    def update_run(self, run_id: str, req: CreateSuperAgentRunRequest) -> SuperAgentRun:
        run = self.get_run(run_id)
        if not run:
            raise ValueError(f"Super Agent run not found: {run_id}")
        if run.status == SuperAgentStatus.RUNNING:
            raise ValueError(f"Super Agent run is already running: {run_id}")

        run.name = (req.name or "").strip() or run.name or "Super Agent Run"
        run.objective = req.objective
        run.processing_mode = req.processing_mode or "OPTIMAL"
        run.input_mode = req.input_mode
        run.source_review_id = req.source_review_id
        run.requested_route = req.requested_route
        run.review_mode = req.review_mode
        run.materials = req.materials
        run.route_decision = None
        run.classification = dict(req.classification) if req.classification else {}
        run.structured_bundle = StructuredReviewBundle()
        run.review_plus_result = {}
        run.gnc_review_result = {}
        run.report_markdown = ""
        run.report_artifact = {}
        run.trace_report = SuperAgentTraceReport()
        run.quality_report = SuperAgentQualityReport()
        run.skill_traces = []
        run.completed_steps = []
        run.status = SuperAgentStatus.DRAFT
        run.error = ""
        self.checkpoint_run(run)
        if req.execute:
            return self.execute_run(run.run_id, request=req)
        return run

    def get_run(self, run_id: str) -> Optional[SuperAgentRun]:
        with self._lock:
            run = self._store.get(run_id)
        if run is None:
            run = self._load_run_from_disk(run_id)
        if run is None:
            return None
        return self._interrupt_if_stale_running(run)

    def list_runs(self) -> list[SuperAgentRun]:
        self._load_all_runs()
        with self._lock:
            runs = list(self._store.values())
        refreshed = [self._interrupt_if_stale_running(run) for run in runs]
        return sorted(refreshed, key=lambda item: item.updated_at, reverse=True)

    def _collect_gnc_review_ids(self, run: SuperAgentRun) -> list[str]:
        ids: set[str] = set()
        if run.route_decision and run.route_decision.gnc_review_id:
            ids.add(str(run.route_decision.gnc_review_id).strip())
        gnc_result = run.gnc_review_result or {}
        for key in ("gnc_review_id", "review_id"):
            value = str(gnc_result.get(key) or "").strip()
            if value:
                ids.add(value)
        if run.input_mode == SuperAgentInputMode.EXISTING_GNC_REVIEW and run.source_review_id:
            ids.add(str(run.source_review_id).strip())
        return sorted(item for item in ids if item)

    def delete_run(self, run_id: str, *, force: bool = False) -> dict:
        run = self.get_run(run_id)
        if not run:
            return {"deleted": False, "run_id": run_id}

        if (not force) and run.status == SuperAgentStatus.RUNNING:
            raise ValueError("Super Agent 任务正在执行中，不能删除")

        removed_files: list[str] = []
        cascaded: dict[str, Any] = {"review_plus_id": "", "gnc_review_ids": []}

        review_plus_id = str(run.source_review_id or "").strip()
        if review_plus_id:
            try:
                from data_agent.review_plus.service import get_review_plus_service

                rp_result = get_review_plus_service().delete_review(review_plus_id, force=force)
                cascaded["review_plus_id"] = review_plus_id
                removed_files.extend(rp_result.get("removed_files") or [])
            except Exception as exc:
                logger.warning("[SuperAgent] Failed to cascade delete Review-Plus %s: %s", review_plus_id, exc)

        gnc_ids = self._collect_gnc_review_ids(run)
        if gnc_ids:
            try:
                from data_agent.api.gnc_review_router import get_gnc_review_service

                gnc_svc = get_gnc_review_service()
                for gnc_id in gnc_ids:
                    gnc_result = gnc_svc.delete_review(gnc_id, force=force)
                    removed_files.extend(gnc_result.get("removed_files") or [])
                cascaded["gnc_review_ids"] = gnc_ids
            except Exception as exc:
                logger.warning("[SuperAgent] Failed to cascade delete GNC tasks %s: %s", gnc_ids, exc)

        upload_paths = [
            SUPER_AGENT_UPLOAD_DIR / run_id,
            SUPER_AGENT_UPLOAD_DIR / "super_agent" / run_id,
        ]
        removed_files.extend(remove_task_artifacts(run_id, *upload_paths))

        removed_files.extend(
            remove_task_artifacts(
                run_id,
                run_dir(self._DATA_DIR, run_id),
                legacy_run_json_path(self._DATA_DIR, run_id),
                RUNS_DIR / "task_boards" / f"{run_id}.json",
            )
        )

        plan_id = str(getattr(run, "plan_id", "") or "").strip()
        if not plan_id:
            phase_artifacts = run.phase_artifacts or {}
            for key in ("execution", "document_parse", "parse"):
                artifact = phase_artifacts.get(key) or {}
                if isinstance(artifact, dict):
                    candidate = str(artifact.get("plan_id") or "").strip()
                    if candidate:
                        plan_id = candidate
                        break
        if plan_id:
            try:
                from data_agent.agents.orchestrator.checkpoint import get_checkpoint_store
                from data_agent.core.config import TRACES_DIR

                trace_paths = [
                    TRACES_DIR / f"{plan_id}.json",
                    RUNS_DIR / f"{plan_id}.json",
                ]
                removed_files.extend(remove_task_artifacts(run_id, *trace_paths))
                get_checkpoint_store().delete(plan_id)
            except Exception as exc:
                logger.warning(
                    "[SuperAgent] Failed to delete trace/checkpoint for plan %s: %s",
                    plan_id,
                    exc,
                )

        with self._lock:
            self._store.pop(run_id, None)

        logger.info(
            "[SuperAgent] Deleted run: %s, force=%s, removed=%s, cascaded=%s",
            run_id,
            force,
            len(removed_files),
            cascaded,
        )
        return {
            "deleted": True,
            "run_id": run_id,
            "force": force,
            "removed_files": removed_files,
            "cascaded": cascaded,
        }

    def resume_run(self, run_id: str) -> SuperAgentRun:
        run = self.get_run(run_id)
        if not run:
            raise ValueError(f"Super Agent run not found: {run_id}")
        if run.status == SuperAgentStatus.RUNNING:
            raise ValueError(f"Super Agent run is already running: {run_id}")
        if run.status not in {
            SuperAgentStatus.INTERRUPTED,
            SuperAgentStatus.FAILED,
            SuperAgentStatus.DRAFT,
        }:
            raise ValueError(
                f"Super Agent run cannot be resumed: {run_id} (status={run.status.value})"
            )
        if (
            run.status == SuperAgentStatus.DRAFT
            and not run.materials
            and not run.source_review_id
        ):
            raise ValueError(f"Super Agent run has nothing to resume: {run_id}")

        run.error = ""
        with self._lock:
            self._interrupt_requested.discard(run_id)
        run.status = SuperAgentStatus.RUNNING
        self.checkpoint_run(run)
        return run

    def mark_run_running(self, run_id: str) -> SuperAgentRun:
        run = self.get_run(run_id)
        if not run:
            raise ValueError(f"Super Agent run not found: {run_id}")
        run.status = SuperAgentStatus.RUNNING
        self.checkpoint_run(run)
        return run

    def save_wizard_checkpoint(
        self,
        run_id: str,
        req: SaveWizardCheckpointRequest,
    ) -> SuperAgentRun:
        """Persist draft wizard progress.

        wizard_step semantics:
        1 upload, 2 classify_and_route, 3 document_parse,
        4 document_review, 5 review_results
        """
        run = self.get_run(run_id)
        if not run:
            raise ValueError(f"Super Agent run not found: {run_id}")
        if run.status != SuperAgentStatus.DRAFT:
            raise ValueError(
                f"Super Agent run wizard checkpoint only allowed for draft: {run_id} (status={run.status.value})"
            )

        if req.materials is not None and materials_changed(run.materials, req.materials):
            invalidate_wizard_from_phase(run, from_step=2)

        from data_agent.super_agent.wizard_phases import WIZARD_STEP_PHASE

        if req.wizard_step is not None:
            if req.wizard_step < run.wizard_step:
                run.wizard_step = req.wizard_step
                phase_id = WIZARD_STEP_PHASE.get(req.wizard_step)
                if phase_id:
                    run.current_phase = phase_id
                    run.phase_status = "in_progress"
            else:
                run.wizard_step = max(run.wizard_step, req.wizard_step)

        self._phases.upload.apply_wizard_checkpoint(run, req)
        self._phases.classify_and_route.apply_wizard_checkpoint(run, req)
        self._phases.document_parse.apply_wizard_checkpoint(run, req)

        if req.wizard_step is not None and not run.current_phase:
            phase_id = WIZARD_STEP_PHASE.get(req.wizard_step)
            if phase_id:
                run.current_phase = phase_id
                run.phase_status = "in_progress"

        self.checkpoint_run(run)
        return run

    # ------------------------------------------------------------------
    # Phase delegations
    # ------------------------------------------------------------------

    def classify_run_materials(self, run_id: str) -> dict[str, Any]:
        return self._phases.classify_and_route.classify_run_materials(run_id)

    def classify_task(
        self,
        run: SuperAgentRun,
        *,
        request: CreateSuperAgentRunRequest | None = None,
    ) -> SuperAgentRouteDecision:
        return self._phases.classify_and_route.classify_task(run, request=request)

    def _classify_materials(
        self,
        run: SuperAgentRun,
        materials: list[SuperAgentMaterial] | list[dict[str, Any]],
    ) -> dict[str, Any]:
        return self._phases.classify_and_route.classify_materials(run, materials)

    def route_review_task(
        self,
        run: SuperAgentRun,
        *,
        request: CreateSuperAgentRunRequest | None = None,
    ) -> SuperAgentRouteDecision:
        return self._phases.classify_and_route.route_review_task(run, request=request)

    def resolve_run_material_source(self, run_id: str, file_name: str) -> tuple[Path, str]:
        return self._phases.upload.resolve_run_material_source(run_id, file_name)

    def resolve_run_material_figure(self, run_id: str, file_name: str, block_id: str) -> Path:
        return self._phases.upload.resolve_run_material_figure(run_id, file_name, block_id)

    def preview_parse_from_run(self, run_id: str, *, force_reparse: bool = False) -> dict[str, Any]:
        return self._phases.document_parse.preview_parse_from_run(
            run_id,
            force_reparse=force_reparse,
        )

    def preview_parse_materials(
        self,
        uploads: list[tuple[str, bytes]],
        *,
        objective: str = "",
        processing_mode: str = "OPTIMAL",
        parser_type: str = "auto",
        mineru_parse_mode: str = "",
        known_classification: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._phases.document_parse.preview_parse_materials(
            uploads,
            objective=objective,
            processing_mode=processing_mode,
            parser_type=parser_type,
            mineru_parse_mode=mineru_parse_mode,
            known_classification=known_classification,
        )

    def parse_run(
        self,
        run_id: str,
        req: SuperAgentParseRunRequest | None = None,
    ) -> SuperAgentParseRunResponse:
        """Independent parse API — delegates to document_parse phase handler."""
        options = req or SuperAgentParseRunRequest()
        run = self.get_run(run_id)
        if not run:
            raise ValueError(f"Super Agent run not found: {run_id}")
        request = self.build_execution_request(run) if options.include_structure else None
        payload = self._phases.document_parse.execute_parse_for_run(
            run_id,
            include_structure=options.include_structure,
            force_reparse=options.force_reparse,
            request=request,
        )
        return SuperAgentParseRunResponse.model_validate(payload)

    def reset_review_execution_state(self, run: SuperAgentRun) -> None:
        """Clear prior review outputs so skip_reparse rerun can re-execute review skills."""
        run.completed_steps = [
            step_id for step_id in run.completed_steps if step_id not in REVIEW_EXECUTION_SKILL_IDS
        ]
        run.skill_traces = [
            trace for trace in run.skill_traces if trace.skill_id not in REVIEW_EXECUTION_SKILL_IDS
        ]
        run.review_plus_result = {}
        run.gnc_review_result = {}
        if isinstance(run.classification, dict):
            run.classification.pop("smart_review_plan", None)
            run.classification.pop("smart_task_board", None)
            run.classification.pop("smart_task_board_summary", None)
            for key in (
                "route_decision_source",
                "post_parse_route",
                "post_parse_reason",
                "final_recommended_route",
            ):
                run.classification.pop(key, None)
            review_plan = run.classification.get("review_plan")
            if isinstance(review_plan, dict):
                for key in (
                    "smart_primary_path",
                    "smart_specialist_ids",
                    "smart_dispatch_reasons",
                    "smart_review_plan",
                    "smart_task_board_summary",
                ):
                    review_plan.pop(key, None)
        if isinstance(run.parse_preview, dict):
            preview_classification = run.parse_preview.get("classification")
            if isinstance(preview_classification, dict):
                for key in (
                    "route_decision_source",
                    "post_parse_route",
                    "post_parse_reason",
                    "final_recommended_route",
                ):
                    preview_classification.pop(key, None)
                preview_classification.update(dict(run.classification or {}))
                run.parse_preview["classification"] = preview_classification
        run.route_decision = None
        run.current_phase = "document_review"
        run.phase_status = "in_progress"
        run.error = ""

    def prepare_review_run(
        self,
        run_id: str,
        req: SuperAgentReviewRunRequest | None = None,
    ) -> SuperAgentRun:
        """Validate parse artifact and mark run running before async review execution."""
        from data_agent.parsing.artifact_builder import is_parse_artifact_complete

        options = req or SuperAgentReviewRunRequest()
        run = self.get_run(run_id)
        if not run:
            raise ValueError(f"Super Agent run not found: {run_id}")
        if run.status == SuperAgentStatus.RUNNING:
            raise ValueError(f"Super Agent run is already running: {run_id}")

        prior_status = run.status
        force_rerun = options.force_rerun or prior_status in {
            SuperAgentStatus.COMPLETED,
            SuperAgentStatus.LIMITED,
            SuperAgentStatus.FAILED,
            SuperAgentStatus.INTERRUPTED,
        }
        if force_rerun:
            self.reset_review_execution_state(run)

        parse_artifact = dict(run.structured_bundle.parse_artifact or {})
        if not parse_artifact and isinstance(run.parse_preview, dict):
            parse_artifact = dict(run.parse_preview.get("parse_artifact") or {})
        if not is_parse_artifact_complete(parse_artifact):
            raise ValueError("请先完成文档解析（parse artifact 不完整或缺失）")

        if options.review_mode is not None:
            run.review_mode = options.review_mode
        if options.requested_route is not None:
            run.requested_route = options.requested_route
            run.route_decision = None
        if options.objective is not None:
            run.objective = str(options.objective).strip()

        from data_agent.super_agent.post_parse_router import ensure_post_parse_route_decision

        ensure_post_parse_route_decision(run)

        run.error = ""
        with self._lock:
            self._interrupt_requested.discard(run_id)
        run.status = SuperAgentStatus.RUNNING
        if force_rerun:
            options.force_rerun = True
        self.checkpoint_run(run)
        return run

    def execute_review_run(
        self,
        run_id: str,
        *,
        req: SuperAgentReviewRunRequest | None = None,
    ) -> SuperAgentRun:
        """Execute document_review + review_results without wiping wizard checkpoint state."""
        options = req or SuperAgentReviewRunRequest()
        run = self.get_run(run_id)
        if not run:
            raise ValueError(f"Super Agent run not found: {run_id}")
        if run.status != SuperAgentStatus.RUNNING:
            run = self.prepare_review_run(run_id, req)

        request = self.build_execution_request(run)
        try:
            self._raise_if_interrupt_requested(run.run_id)
            self._phases.document_review.execute_review_for_run(
                run_id,
                request=request,
                skip_reparse=options.skip_reparse,
                force_rerun=options.force_rerun,
            )
            run = self.get_run(run_id)
            if not run:
                raise ValueError(f"Super Agent run not found after review: {run_id}")
            self._raise_if_interrupt_requested(run.run_id)
            ctx = PhaseContext(
                run=run,
                request=request,
                resume=options.skip_reparse,
                decision=run.route_decision,
            )
            self._phases.review_results.execute_pipeline(ctx)
        except RunInterruptedError:
            run = self.get_run(run_id) or run
            run.status = SuperAgentStatus.INTERRUPTED
            if not run.error:
                run.error = MANUAL_INTERRUPT_ERROR
        except Exception as exc:
            agent_debug_log(
                "super_agent/service.py:execute_review_run",
                "execute_review_run caught exception",
                {"run_id": run_id, "error_type": type(exc).__name__, "error": str(exc)[:500]},
                hypothesis_id="D",
            )
            run = self.get_run(run_id) or run
            run.status = SuperAgentStatus.FAILED
            run.error = str(exc)
            run.trace_report.failed_steps.append({"step": "execute_review_run", "error": str(exc)})
        finally:
            run = self.get_run(run_id) or run
            with self._lock:
                if run.run_id in self._interrupt_requested:
                    run.status = SuperAgentStatus.INTERRUPTED
                    if not run.error:
                        run.error = MANUAL_INTERRUPT_ERROR
            run.updated_at = helpers._now()
            with self._lock:
                self._store[run.run_id] = run
            self._save_run(run)
        return run

    def review_run(
        self,
        run_id: str,
        req: SuperAgentReviewRunRequest | None = None,
    ) -> SuperAgentReviewRunResponse:
        """Independent review API — delegates to document_review + review_results."""
        run = self.execute_review_run(run_id, req=req)
        route = run.route_decision.route.value if run.route_decision else ""
        return SuperAgentReviewRunResponse(
            run_id=run.run_id,
            route=route,
            review_plus_result=dict(run.review_plus_result or {}),
            gnc_review_result=dict(run.gnc_review_result or {}),
            structured_bundle=run.structured_bundle,
            skill_traces=list(run.skill_traces),
        )

    def parse_materials(
        self,
        run: SuperAgentRun,
        plan: ParsingPlan,
        *,
        request: CreateSuperAgentRunRequest | None = None,
    ) -> None:
        return self._phases.document_parse.parse_materials(run, plan, request=request)

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
        return self._phases.document_review.execute_skills(
            run,
            decision,
            request=request,
            plan=plan,
            resume=resume,
            force_rerun=force_rerun,
        )

    def bootstrap_review_plus_task(
        self,
        run: SuperAgentRun,
        request: CreateSuperAgentRunRequest,
    ) -> dict[str, Any]:
        return self._phases.document_review.bootstrap_review_plus_task(run, request)

    def structure_materials(
        self,
        run: SuperAgentRun,
        *,
        request: CreateSuperAgentRunRequest | None = None,
    ) -> StructuredReviewBundle:
        return self._phases.document_review.structure_materials(run, request=request)

    def run_review_plus(
        self,
        run: SuperAgentRun,
        *,
        skip_structure: bool = False,
        force_rerun: bool = False,
    ) -> dict[str, Any]:
        return self._phases.document_review.run_review_plus(
            run,
            skip_structure=skip_structure,
            force_rerun=force_rerun,
        )

    def run_gnc_review(
        self,
        run: SuperAgentRun,
        *,
        request: CreateSuperAgentRunRequest | None = None,
        allow_missing: bool = False,
    ) -> dict[str, Any]:
        return self._phases.document_review.run_gnc_review(
            run,
            request=request,
            allow_missing=allow_missing,
        )

    def collect_traces(self, run: SuperAgentRun) -> SuperAgentTraceReport:
        return self._phases.review_results.collect_traces(run)

    def evaluate_quality(self, run: SuperAgentRun) -> SuperAgentQualityReport:
        return self._phases.review_results.evaluate_quality(run)

    def build_report(self, run: SuperAgentRun) -> dict[str, Any]:
        return self._phases.review_results.build_report(run)

    def execute_run(
        self,
        run_id: str,
        *,
        request: CreateSuperAgentRunRequest | None = None,
        resume: bool = False,
    ) -> SuperAgentRun:
        run = self.get_run(run_id)
        if not run:
            raise ValueError(f"Super Agent run not found: {run_id}")
        run.status = SuperAgentStatus.RUNNING
        self.checkpoint_run(run)
        try:
            if request:
                run.review_mode = request.review_mode
                run.materials = [
                    item.model_copy(update={"content_base64": ""})
                    for item in request.materials
                ]

            self._raise_if_interrupt_requested(run.run_id)
            ctx = PhaseContext(run=run, request=request, resume=resume)
            ctx.decision = self._phases.classify_and_route.execute_pipeline(ctx)
            self._raise_if_interrupt_requested(run.run_id)
            self._phases.document_parse.execute_pipeline(ctx)
            self._raise_if_interrupt_requested(run.run_id)
            self._phases.document_review.execute_pipeline(ctx)
            self._raise_if_interrupt_requested(run.run_id)
            self._phases.review_results.execute_pipeline(ctx)
        except RunInterruptedError:
            run.status = SuperAgentStatus.INTERRUPTED
            if not run.error:
                run.error = MANUAL_INTERRUPT_ERROR
        except Exception as exc:
            agent_debug_log(
                "super_agent/service.py:execute_run",
                "execute_run caught exception",
                {"run_id": run.run_id, "error_type": type(exc).__name__, "error": str(exc)[:500]},
                hypothesis_id="D",
            )
            run.status = SuperAgentStatus.FAILED
            run.error = str(exc)
            run.trace_report.failed_steps.append({"step": "execute_run", "error": str(exc)})
        finally:
            with self._lock:
                if run.run_id in self._interrupt_requested:
                    run.status = SuperAgentStatus.INTERRUPTED
                    if not run.error:
                        run.error = MANUAL_INTERRUPT_ERROR
            run.updated_at = helpers._now()
            with self._lock:
                self._store[run.run_id] = run
            self._save_run(run)
        return run

    def capabilities(self) -> SuperAgentCapabilities:
        return SuperAgentCapabilities(
            routes=[
                "review_plus",
                "gnc_review",
                "gnc_review_only",
                "structure_only",
                "hybrid",
                "smart",
            ],
            independent_apis=[
                {
                    "id": "document_parse",
                    "method": "POST",
                    "path": "/api/v1/super-agent/runs/{run_id}/parse",
                    "description": "基于已分类材料产出 parse-only artifact",
                },
                {
                    "id": "document_review",
                    "method": "POST",
                    "path": "/api/v1/super-agent/runs/{run_id}/review",
                    "description": "基于已有 parse artifact 执行审查技能",
                },
            ],
            skills=[
                {
                    "id": "bootstrap_review_plus_task",
                    "name": "材料包自举",
                    "description": "上传材料按显式角色转成 Review-Plus 可执行任务",
                },
                {
                    "id": "structure_materials",
                    "name": "数据结构化专员",
                    "description": "解析、章节树、证据池、检查项抽取",
                },
                {
                    "id": "run_review_plus",
                    "name": "审查执行专员",
                    "description": "委托 Review-Plus workflow 与 Harness",
                },
                {
                    "id": "run_gnc_review",
                    "name": "GNC 委员会专员",
                    "description": "委托 GNC 单文档/多文档专家审查与一致性检查",
                },
                {
                    "id": "collect_traces",
                    "name": "稳定性专员",
                    "description": "汇总 traces、降级与质量评分",
                },
            ],
            reused_components=[
                "parsing/service",
                "parsing/parser_router",
                "review_plus_workflow",
                "ReviewPlusAgentHarness",
                "satellite_review.gnc_workflow",
            ],
        )

    def run_builtin_benchmark(self) -> dict[str, Any]:
        fixture_root = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "review_docs" / "review_plus_full_chain"
        cases = [
            {
                "case_id": "review_plus_full_chain_role_override",
                "name": "Review-Plus 三槽位材料包",
                "request": CreateSuperAgentRunRequest(
                    name="Super Agent benchmark - full chain",
                    objective="验证上传材料包自举、结构化、路由、审查执行、trace 汇总与质量评分。",
                    input_mode=SuperAgentInputMode.UPLOAD,
                    materials=[
                        SuperAgentMaterial(
                            name="检查单.md",
                            content=(fixture_root / "review_rule.md").read_text(encoding="utf-8"),
                            role="checklist",
                            parser_type="local",
                        ),
                        SuperAgentMaterial(
                            name="任务书.md",
                            content=(fixture_root / "requirements_spec.md").read_text(encoding="utf-8"),
                            role="task_book",
                            parser_type="local",
                        ),
                        SuperAgentMaterial(
                            name="被审方案.md",
                            content=(fixture_root / "design_solution.md").read_text(encoding="utf-8"),
                            role="subject_document",
                            parser_type="local",
                        ),
                    ],
                    execute=True,
                ),
                "expected_route": SuperAgentRoute.REVIEW_PLUS.value,
            }
        ]
        results = []
        for case in cases:
            try:
                run = self.create_run(case["request"])
                route = run.route_decision.route.value if run.route_decision else ""
                passed = (
                    route == case["expected_route"]
                    and run.status in {SuperAgentStatus.COMPLETED, SuperAgentStatus.LIMITED}
                    and bool(run.source_review_id)
                    and any(
                        trace.skill_id == "bootstrap_review_plus_task" and trace.status == "completed"
                        for trace in run.skill_traces
                    )
                )
                results.append(
                    {
                        "case_id": case["case_id"],
                        "name": case["name"],
                        "passed": passed,
                        "run_id": run.run_id,
                        "source_review_id": run.source_review_id,
                        "status": run.status.value,
                        "route": route,
                        "expected_route": case["expected_route"],
                        "quality": run.quality_report.model_dump(mode="json"),
                        "degradation_summary": run.trace_report.degradation_summary,
                        "failed_steps": run.trace_report.failed_steps,
                    }
                )
            except Exception as exc:
                results.append(
                    {
                        "case_id": case["case_id"],
                        "name": case["name"],
                        "passed": False,
                        "error": str(exc),
                        "expected_route": case["expected_route"],
                    }
                )
        passed_count = sum(1 for item in results if item.get("passed"))
        return {
            "benchmark_id": "super_agent_builtin_smoke",
            "case_count": len(results),
            "passed_count": passed_count,
            "failed_count": len(results) - passed_count,
            "pass_rate": round(passed_count / max(len(results), 1), 4),
            "coverage": {
                "task_1_data_understanding": [
                    "multi_format_ingestion",
                    "structured_bundle",
                    "evidence_pool",
                    "role_override",
                ],
                "task_2_planning_execution": [
                    "route_review_task",
                    "run_review_plus",
                    "workflow_delegation",
                ],
                "task_3_stability_evaluation": [
                    "collect_traces",
                    "evaluate_quality",
                    "degradation_summary",
                ],
            },
            "results": results,
        }


def get_super_agent_service() -> SuperAgentService:
    return SuperAgentService()
