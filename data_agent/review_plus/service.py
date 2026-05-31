"""
Review-Plus task lifecycle service.

This service is intentionally isolated from the existing GNC review service.
Tasks are cached in memory and persisted to JSON files under aq-aero/data.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

from data_agent.review_plus.task_artifact_cleanup import remove_task_artifacts

from data_agent.review_plus.schemas import (
    CreateReviewPlusRequest,
    ReviewPlusMaterialItem,
    ReviewPlusParserType,
    ReviewPlusMaterialRole,
    ReviewPlusStatus,
    ReviewPlusTask,
)
from data_agent.core.config import PROJECT_ROOT, RUNS_DIR, UPLOAD_DIR, REVIEW_PLUS_REPORTS_DIR, LEGACY_REVIEW_PLUS_REPORTS_DIR
from data_agent.core.agent_debug_log import agent_debug_log
from data_agent.review_plus.material_classifier_service import classify_all_materials
from data_agent.parsing.parser_router import parse_review_plus_material

logger = logging.getLogger(__name__)

_DATA_DIR = RUNS_DIR / "review_plus_tasks"
_UPLOADS_DIR = UPLOAD_DIR / "review_plus"
_DATA_ROOT = PROJECT_ROOT / "storage"
_CHUNKS_DIR = _DATA_ROOT / "chunks"


def _now() -> str:
    return datetime.now().isoformat()


def _sanitize_text(value: str) -> str:
    if not value:
        return ""
    return "".join(ch for ch in value if not 0xD800 <= ord(ch) <= 0xDFFF)


def _safe_upload_name(filename: str) -> str:
    if "\0" in (filename or ""):
        raise ValueError("文件名不能包含 null byte")
    name = _sanitize_text(filename or "").replace("/", "_").replace("\\", "_").strip()
    if not name or name in {".", ".."} or ".." in name:
        raise ValueError("文件名不能为空，且不能包含 '..'")
    if any(ord(ch) < 32 for ch in name):
        raise ValueError("文件名不能包含控制字符")
    return name


class ReviewPlusService:
    """Review-Plus MVP service with JSON-backed task storage."""

    _instance: Optional["ReviewPlusService"] = None
    _DATA_DIR = _DATA_DIR
    _lock = threading.RLock()

    def __new__(cls) -> "ReviewPlusService":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._store = {}
            cls._instance._sequence_store = {}
            cls._instance._load_all_tasks()
        return cls._instance

    def _save_task(self, task: ReviewPlusTask) -> None:
        self._DATA_DIR.mkdir(parents=True, exist_ok=True)
        path = self._DATA_DIR / f"{task.review_plus_id}.json"
        with self._lock:
            self._store[task.review_plus_id] = task
            path.write_text(task.model_dump_json(indent=2), encoding="utf-8")

    def _load_all_tasks(self) -> None:
        self._store = {}
        self._sequence_store = {}
        if not self._DATA_DIR.exists():
            return

        for path in self._DATA_DIR.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if "review_plus_id" not in data and data.get("review_id"):
                    data["review_plus_id"] = data["review_id"]
                task = ReviewPlusTask.model_validate(data)
                self._store[task.review_plus_id] = task
                self._sequence_store[task.review_plus_id] = max(
                    (int(event.get("sequence", 0)) for event in task.events if isinstance(event, dict)),
                    default=0,
                )
            except Exception as exc:
                logger.warning("[ReviewPlus] Failed to load task from %s: %s", path.name, exc)

    def create_review(self, req: CreateReviewPlusRequest) -> ReviewPlusTask:
        task = ReviewPlusTask(
            name=(req.name or "").strip(),
            status=ReviewPlusStatus.DRAFT.value,
        )
        with self._lock:
            self._store[task.review_plus_id] = task
            self._sequence_store[task.review_plus_id] = 0
        self.record_event(task.review_plus_id, "task_created", {"name": task.name})
        logger.info("[ReviewPlus] Created task: %s - %s", task.review_plus_id, task.name)
        return task

    def list_reviews(self) -> list[ReviewPlusTask]:
        with self._lock:
            return sorted(self._store.values(), key=lambda item: item.updated_at, reverse=True)

    def get_review(self, review_id: str) -> Optional[ReviewPlusTask]:
        with self._lock:
            task = self._store.get(review_id)
        if task is None:
            _json_path = self._DATA_DIR / f"{review_id}.json"
            agent_debug_log(
                "review_plus_service.py:get_review",
                "task not found",
                {
                    "review_id": review_id,
                    "json_exists": _json_path.exists(),
                    "store_keys": list(self._store.keys()),
                },
                hypothesis_id="B",
                run_id="post-fix",
            )
        return task

    def update_status(
        self,
        review_id: str,
        status: ReviewPlusStatus,
        *,
        event_type: str = "status_changed",
        payload: Optional[dict] = None,
    ) -> Optional[ReviewPlusTask]:
        with self._lock:
            task = self.get_review(review_id)
            if not task:
                return None
            previous_status = task.status
            task.status = status.value
            task.updated_at = _now()
            self.record_event(
                review_id,
                event_type,
                {
                    "from_status": previous_status,
                    "to_status": task.status,
                    **(payload or {}),
                },
            )
            return task

    def record_event(self, review_id: str, event_type: str, payload: Optional[dict] = None) -> dict:
        with self._lock:
            task = self.get_review(review_id)
            if not task:
                return {}
            sequence = self._sequence_store.get(review_id, 0) + 1
            self._sequence_store[review_id] = sequence
            event = {
                "sequence": sequence,
                "type": event_type,
                "payload": payload or {},
                "created_at": _now(),
            }
            task.events.append(event)
            task.updated_at = event["created_at"]
            self._save_task(task)
            return event

    def upload_materials(
        self,
        review_id: str,
        uploads: list[tuple[str, bytes]],
        *,
        parser_type: str = "local",
    ) -> Optional[ReviewPlusTask]:
        task = self.get_review(review_id)
        if not task:
            return None
        parser_value = parser_type.value if isinstance(parser_type, ReviewPlusParserType) else str(parser_type or "")
        if parser_value not in {item.value for item in ReviewPlusParserType}:
            raise ValueError(f"不支持的解析器类型: {parser_type}")
        if not uploads:
            return task

        uploads_dir = _UPLOADS_DIR / review_id
        uploads_dir.mkdir(parents=True, exist_ok=True)

        from data_agent.parsing.material_preview import extract_material_preview
        from data_agent.services.task_classifier import classify_batch, resolve_parsing_tier

        material_by_name = {material.name: material for material in task.materials}
        uploaded_names: list[str] = []
        saved_files: list[tuple[str, Path]] = []

        for filename, raw_content in uploads:
            safe_name = _safe_upload_name(filename)
            file_path = uploads_dir / safe_name
            file_path.write_bytes(raw_content or b"")
            saved_files.append((safe_name, file_path))
            uploaded_names.append(safe_name)

        preview_materials: list[dict[str, str]] = []
        for safe_name, file_path in saved_files:
            preview = extract_material_preview(str(file_path), safe_name)
            preview_materials.append(
                {
                    "file_name": safe_name,
                    "file_path": str(file_path),
                    "content": preview,
                    "preview_content": preview,
                }
            )
        classification = classify_batch(
            preview_materials,
            objective=task.name or task.scenario or "",
        )
        role_by_name = {item.file_name: item for item in classification.material_roles}
        role_values = {role.value for role in ReviewPlusMaterialRole}

        for safe_name, file_path in saved_files:
            role_item = role_by_name.get(safe_name)
            role_value = role_item.role if role_item else ReviewPlusMaterialRole.UNKNOWN.value
            tier = resolve_parsing_tier(role_value, safe_name, default_parser_type=parser_value)
            preview_text = extract_material_preview(str(file_path), safe_name)
            role_enum = (
                ReviewPlusMaterialRole(role_value)
                if role_value in role_values
                else ReviewPlusMaterialRole.UNKNOWN
            )
            material_by_name[safe_name] = ReviewPlusMaterialItem(
                name=safe_name,
                file_type=Path(safe_name).suffix.lower().lstrip(".") or "txt",
                content=_sanitize_text(preview_text),
                file_path=str(file_path),
                parser_type=str(tier["parser_type"] or parser_value),
                parser_name="material_preview",
                warnings=[],
                parse_status="preview",
                role=role_enum,
                role_confidence=float(role_item.confidence if role_item else 0.0),
                role_reason=str(role_item.reason if role_item else ""),
                parser_trace=[
                    {
                        "kind": "parsing_tier",
                        "tier": tier["tier"],
                        "role": role_value,
                        "parser_type": tier["parser_type"],
                        "processing_mode": tier["processing_mode"],
                    },
                    {
                        "kind": "material_preview",
                        "parser": "material_preview",
                        "status": "preview",
                        "file_name": safe_name,
                    },
                ],
            )

        with self._lock:
            task.materials = list(material_by_name.values())
            task.check_items = []
            task.parsed_documents = []
            task.parse_artifact = {}
            task.section_tree = {}
            task.evidence_pool = {}
            task.document_ir = {}
            task.object_registry = {}
            task.document_format_review = {}
            task.chief_review_plan = {}
            task.specialist_reviews = []
            task.gatekeeping_result = {}
            task.traceability_result = {}
            task.cross_document_review_items = []
            task.coverage_matrix = {}
            task.agent_run_traces = []
            task.section_mappings = []
            task.findings = []
            task.report = None
            task.report_markdown = ""
            task.report_file_path = ""
            task.parser_traces = [
                trace
                for material in task.materials
                for trace in (material.parser_trace or [])
            ]
        self.update_status(
            review_id,
            ReviewPlusStatus.MATERIALS_UPLOADED,
            event_type="materials_uploaded",
            payload={
                "uploaded_names": uploaded_names,
                "material_count": len(task.materials),
                "task_route": classification.route,
            },
        )
        self.update_status(
            review_id,
            ReviewPlusStatus.CLASSIFIED,
            event_type="material_classification_completed",
            payload={
                "classifier": "shared_task_classifier",
                "task_route": classification.route,
                "roles": [
                    {
                        "name": material.name,
                        "role": material.role.value if isinstance(material.role, ReviewPlusMaterialRole) else material.role,
                        "confidence": material.role_confidence,
                        "parsing_tier": next(
                            (
                                trace.get("tier")
                                for trace in (material.parser_trace or [])
                                if trace.get("kind") == "parsing_tier"
                            ),
                            None,
                        ),
                    }
                    for material in task.materials
                ],
            },
        )
        self._auto_confirm_classified_roles(review_id)
        self.recheck_gatekeeping(review_id)
        return self.get_review(review_id)

    def parse_materials(
        self,
        review_id: str,
        *,
        force_reparse: bool = False,
    ) -> Optional[ReviewPlusTask]:
        """Step 3: full document parse; persist parse-only artifact (no structuring)."""
        from data_agent.parsing.artifact_builder import is_parse_artifact_complete
        from data_agent.parsing.parse_artifacts import build_parse_only_artifact_from_materials

        task = self.get_review(review_id)
        if not task:
            return None
        if not task.materials:
            raise ValueError("请先上传送审材料")

        parse_artifact = getattr(task, "parse_artifact", None) or {}
        if (
            not force_reparse
            and isinstance(parse_artifact, dict)
            and is_parse_artifact_complete(parse_artifact)
        ):
            return task

        self.update_status(
            review_id,
            ReviewPlusStatus.PARSING,
            event_type="document_parsing_started",
            payload={"force_reparse": force_reparse},
        )

        parse_inputs: list[dict[str, str]] = []
        for material in task.materials:
            if not material.file_path:
                raise ValueError(f"材料缺少原始文件路径，无法解析: {material.name}")
            parse_inputs.append(
                {
                    "file_path": material.file_path,
                    "file_name": material.name,
                    "parser_type": str(material.parser_type or "auto"),
                }
            )

        parse_only = build_parse_only_artifact_from_materials(parse_inputs)
        parse_payload = parse_only.model_dump(mode="json")
        parse_payload["pipeline_step"] = "document_parse"
        parsed_by_name = {
            str(item.get("file_name") or ""): item
            for item in (parse_payload.get("parsed_documents") or [])
            if isinstance(item, dict)
        }

        with self._lock:
            for material in task.materials:
                item = parsed_by_name.get(material.name)
                if not item:
                    continue
                document = item.get("document") if isinstance(item.get("document"), dict) else {}
                content_parts: list[str] = []
                for block in document.get("blocks") or []:
                    if not isinstance(block, dict):
                        continue
                    text = str(block.get("text") or "").strip()
                    if text:
                        content_parts.append(text)
                if content_parts:
                    material.content = _sanitize_text("\n".join(content_parts)[:8000])
                material.file_type = str(
                    item.get("file_type") or document.get("file_type") or material.file_type or ""
                )
                material.parser_name = str(
                    item.get("parser_name") or document.get("parser_name") or material.parser_name or ""
                )
                material.parse_status = str(
                    item.get("parse_status") or document.get("parse_status") or "ok"
                )
                material.warnings = list(item.get("warnings") or document.get("warnings") or [])
                material.parser_trace = list(item.get("parser_fallback_logs") or []) or material.parser_trace

            task.parse_artifact = parse_payload
            task.document_ir = parse_payload.get("document_ir") or {}
            task.section_tree = {}
            task.evidence_pool = {}
            task.parsed_documents = []
            task.parser_traces = [
                trace
                for material in task.materials
                for trace in (material.parser_trace or [])
            ]
            task.updated_at = _now()
            self._save_task(task)

        self.update_status(
            review_id,
            ReviewPlusStatus.PARSED,
            event_type="document_parsing_completed",
            payload={
                "batch_summary": parse_payload.get("batch_summary") or {},
                "force_reparse": force_reparse,
            },
        )
        return self.get_review(review_id)

    def reparse_material(
        self,
        review_id: str,
        material_name: str,
        *,
        parser_type: str = "auto",
    ) -> Optional[ReviewPlusTask]:
        task = self.get_review(review_id)
        if not task:
            return None
        parser_value = parser_type.value if isinstance(parser_type, ReviewPlusParserType) else str(parser_type or "")
        if parser_value not in {item.value for item in ReviewPlusParserType}:
            raise ValueError(f"不支持的解析器类型: {parser_type}")

        material = next((item for item in task.materials if item.name == material_name), None)
        if not material:
            raise ValueError(f"Material '{material_name}' not found")
        if not material.file_path:
            raise ValueError(f"材料缺少原始文件路径，无法重新解析: {material_name}")

        file_path = Path(material.file_path)
        if not file_path.exists():
            raise ValueError(f"原始文件不存在，无法重新解析: {material_name}")

        parsed, parser_trace = parse_review_plus_material(str(file_path), material.name, parser_type=parser_value)
        with self._lock:
            material.file_type = parsed.file_type
            material.content = _sanitize_text(parsed.content)
            material.parser_type = parser_value
            material.parser_name = getattr(parsed, "parser_name", "")
            material.warnings = list(getattr(parsed, "warnings", []))
            material.parse_status = parsed.parse_status
            material.parser_trace = parser_trace
            task.parser_traces = [
                trace
                for item in task.materials
                for trace in (item.parser_trace or [])
            ]
            task.updated_at = _now()
            self._save_task(task)

        task = self.invalidate_derived_results(review_id) or task
        task = self.recheck_gatekeeping(review_id) or task
        self.record_event(
            review_id,
            "material_reparsed",
            {"material_name": material_name, "parser_type": parser_value, "parse_status": parsed.parse_status},
        )
        return self.parse_materials(review_id, force_reparse=True) or task

    def _auto_confirm_classified_roles(self, review_id: str, *, min_confidence: float = 0.75) -> None:
        """高置信度自动判定结果默认视为已确认，减少批量上传后的手工操作。"""
        task = self.get_review(review_id)
        if not task:
            return
        changed = False
        with self._lock:
            for material in task.materials:
                role_value = (
                    material.role.value
                    if isinstance(material.role, ReviewPlusMaterialRole)
                    else str(material.role or "")
                )
                if role_value == ReviewPlusMaterialRole.UNKNOWN.value:
                    continue
                if material.role_confirmed:
                    continue
                if float(material.role_confidence or 0.0) < min_confidence:
                    continue
                material.role_confirmed = True
                if not material.role_reason:
                    material.role_reason = "系统根据文件名与内容自动判定"
                changed = True
            if changed:
                task.updated_at = _now()
                self._save_task(task)

    def classify_materials(self, review_id: str) -> Optional[ReviewPlusTask]:
        task = self.get_review(review_id)
        if not task:
            return None
        self.update_status(review_id, ReviewPlusStatus.CLASSIFYING, event_type="material_classification_started")
        
        from data_agent.services.task_classifier import classify_batch

        agent_debug_log(
            "service.py:classify_materials",
            "use shared task classifier",
            {"review_id": review_id, "material_count": len(task.materials)},
            hypothesis_id="E",
        )
        shared = classify_batch(
            [material.model_dump() for material in task.materials],
            objective=task.name or task.scenario or "",
        )
        results = [
            (
                ReviewPlusMaterialRole(item.role)
                if item.role in {role.value for role in ReviewPlusMaterialRole}
                else ReviewPlusMaterialRole.UNKNOWN,
                item.confidence,
                item.reason,
            )
            for item in shared.material_roles
        ]

        with self._lock:
            for material, (role, confidence, reason) in zip(task.materials, results):
                material.role = role
                material.role_confidence = confidence
                material.role_reason = reason
        return self.update_status(
            review_id,
            ReviewPlusStatus.CLASSIFIED,
            event_type="material_classification_completed",
            payload={
                "roles": [
                    {
                        "name": material.name,
                        "role": material.role.value if isinstance(material.role, ReviewPlusMaterialRole) else material.role,
                        "confidence": material.role_confidence,
                    }
                    for material in task.materials
                ]
            },
        )

    def start_review(self, review_id: str) -> Optional[ReviewPlusTask]:
        task = self.get_review(review_id)
        if not task:
            return None
        if not task.materials:
            raise ValueError("请先上传送审材料")

        from data_agent.review_plus.gatekeeping_adapter import evaluate_review_plus_gatekeeping

        gate_result = evaluate_review_plus_gatekeeping(task)
        with self._lock:
            task.gatekeeping_result = gate_result.model_dump()
            task.updated_at = _now()
            if gate_result.gate_status == "blocked":
                task.status = ReviewPlusStatus.BLOCKED.value
                self._save_task(task)
            elif gate_result.gate_status == "limited":
                task.status = ReviewPlusStatus.LIMITED_PASS.value
                self._save_task(task)
            else:
                task.status = ReviewPlusStatus.READY.value
                self._save_task(task)
        if gate_result.gate_status == "blocked":
            raise ValueError(f"准入未通过: {'; '.join(gate_result.blocking_reasons)}")

        self.record_event(review_id, "review_start_requested", {"status": task.status})
        return task

    def invalidate_derived_results(self, review_id: str) -> Optional[ReviewPlusTask]:
        task = self.get_review(review_id)
        if not task:
            return None
        with self._lock:
            task.gatekeeping_result = {}
            task.traceability_result = {}
            task.cross_document_review_items = []
            task.coverage_matrix = {}
            task.agent_run_traces = []
            task.parse_artifact = {}
            task.document_ir = {}
            task.section_tree = {}
            task.document_format_review = {}
            task.chief_review_plan = {}
            task.specialist_reviews = []
            task.check_items = []
            task.section_mappings = []
            task.findings = []
            task.report = None
            # 回退状态到 classified，使后续流程可重新触发（门禁→审查→追溯→报告）
            if task.status not in (
                ReviewPlusStatus.DRAFT.value,
                ReviewPlusStatus.MATERIALS_UPLOADED.value,
            ):
                task.status = ReviewPlusStatus.CLASSIFIED.value
            task.updated_at = _now()
            self._save_task(task)
        self.record_event(review_id, "derived_results_invalidated", {"reason": "材料角色或元数据变更"})
        return task

    def invalidate_review_execution_results(self, review_id: str) -> Optional[ReviewPlusTask]:
        """Clear review outputs while preserving parse/structure materials for safe rerun."""
        task = self.get_review(review_id)
        if not task:
            return None
        with self._lock:
            task.gatekeeping_result = {}
            task.traceability_result = {}
            task.cross_document_review_items = []
            task.coverage_matrix = {}
            task.agent_run_traces = []
            task.document_format_review = {}
            task.chief_review_plan = {}
            task.specialist_reviews = []
            task.check_items = []
            task.section_mappings = []
            task.findings = []
            task.report = None
            if task.status not in (
                ReviewPlusStatus.DRAFT.value,
                ReviewPlusStatus.MATERIALS_UPLOADED.value,
                ReviewPlusStatus.CLASSIFIED.value,
            ):
                task.status = ReviewPlusStatus.CLASSIFIED.value
            task.updated_at = _now()
            self._save_task(task)
        self.record_event(review_id, "review_execution_invalidated", {"reason": "super_agent_rerun"})
        return task

    def recheck_gatekeeping(self, review_id: str) -> Optional[ReviewPlusTask]:
        task = self.get_review(review_id)
        if not task:
            return None

        from data_agent.review_plus.gatekeeping_adapter import evaluate_review_plus_gatekeeping

        gate_result = evaluate_review_plus_gatekeeping(task)
        with self._lock:
            task.gatekeeping_result = gate_result.model_dump()
            task.updated_at = _now()
            if gate_result.gate_status == "blocked":
                task.status = ReviewPlusStatus.BLOCKED.value
            elif task.status == ReviewPlusStatus.BLOCKED.value:
                task.status = ReviewPlusStatus.MATERIALS_UPLOADED.value
            self._save_task(task)
        self.record_event(
            review_id,
            "gatekeeping_rechecked",
            {
                "gate_status": gate_result.gate_status,
                "can_start_review": gate_result.can_start_review,
            },
        )
        return task

    def continue_started_review(self, review_id: str) -> Optional[ReviewPlusTask]:
        task = self.get_review(review_id)
        if not task:
            return None
        from data_agent.workflows.review_plus_workflow import run_review_plus_workflow

        run_review_plus_workflow(review_id)
        return self.get_review(review_id)

    def restart_review_from_source(self, review_id: str) -> Optional[ReviewPlusTask]:
        previous = self.get_review(review_id)
        previous_status = previous.status if previous else ""
        task = self.invalidate_derived_results(review_id)
        if not task:
            return None
        self.record_event(review_id, "review_restart_requested", {"from_status": previous_status})
        return self.start_review(review_id)

    def get_classification(self, review_id: str) -> Optional[list[dict]]:
        task = self.get_review(review_id)
        if not task:
            return None
        return [
            {
                "name": material.name,
                "role": material.role.value if isinstance(material.role, ReviewPlusMaterialRole) else material.role,
                "confidence": material.role_confidence,
                "reason": material.role_reason,
            }
            for material in task.materials
        ]

    def get_check_items(self, review_id: str) -> Optional[list[dict]]:
        task = self.get_review(review_id)
        if not task:
            return None
        return [item.model_dump() for item in task.check_items]

    def get_events(self, review_id: str) -> Optional[list[dict]]:
        task = self.get_review(review_id)
        if not task:
            return None
        return list(task.events)

    def delete_review(self, review_id: str, force: bool = False) -> dict:
        task = self.get_review(review_id)
        if not task:
            return {"deleted": False, "review_plus_id": review_id}

        running_statuses = {
            ReviewPlusStatus.PARSING.value,
            ReviewPlusStatus.CLASSIFYING.value,
            ReviewPlusStatus.STRUCTURING.value,
            ReviewPlusStatus.RULE_EXTRACTING.value,
            ReviewPlusStatus.MAPPING.value,
            ReviewPlusStatus.REVIEWING.value,
            ReviewPlusStatus.TRACEABILITY_BUILDING.value,
            ReviewPlusStatus.REPORTING.value,
            ReviewPlusStatus.GATEKEEPING.value,
        }
        if (not force) and task.status in running_statuses:
            raise ValueError("审查任务正在执行中，不能删除")

        removed_files: list[str] = []
        extra_paths: list[Path] = [
            REVIEW_PLUS_REPORTS_DIR / f"{review_id}.md",
            LEGACY_REVIEW_PLUS_REPORTS_DIR / f"{review_id}.md",
        ]
        report_file_path = getattr(task, "report_file_path", "") or ""
        if report_file_path:
            extra_paths.append(Path(report_file_path))

        with self._lock:
            self._store.pop(review_id, None)
            self._sequence_store.pop(review_id, None)

        removed_files.extend(
            remove_task_artifacts(
                review_id,
                self._DATA_DIR / f"{review_id}.json",
                _UPLOADS_DIR / review_id,
                _CHUNKS_DIR / review_id,
                *extra_paths,
            )
        )

        logger.info("[ReviewPlus] Deleted task: %s, force=%s, removed=%s", review_id, force, len(removed_files))
        return {
            "deleted": True,
            "review_plus_id": review_id,
            "force": force,
            "removed_files": removed_files,
        }


def get_review_plus_service() -> ReviewPlusService:
    return ReviewPlusService()
