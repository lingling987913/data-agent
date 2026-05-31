"""Wizard phase: classify_and_route."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from pathlib import Path
from typing import Any, TYPE_CHECKING

from data_agent.super_agent import helpers
from data_agent.super_agent.phases.base import advance_wizard_phase
from data_agent.super_agent.route_policy import tools_for_route
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

_CLASSIFICATION_ROUTE_MAP = {
    "review_plus": "review_plus",
    "gnc_review": "gnc_review",
    "parse_only": "smart",
}

_EXECUTION_ROUTE_MAP = {
    "review_plus": SuperAgentRoute.REVIEW_PLUS,
    "gnc_review": SuperAgentRoute.GNC_REVIEW_ONLY,
    "hybrid": SuperAgentRoute.HYBRID,
    "smart": SuperAgentRoute.SMART,
}


def _infer_classification_labels(
    normalized: list[dict[str, Any]],
    material_roles: list[dict[str, Any]],
    recommended_route: str,
) -> tuple[str, str]:
    """Infer human-readable doc_type/domain from roles and filenames (no LLM)."""
    from data_agent.review_plus.schemas import ReviewPlusMaterialRole

    roles = {str(item.get("role") or "").lower() for item in material_roles}
    names = " ".join(
        str(m.get("file_name") or m.get("filename") or m.get("name") or "")
        for m in normalized
    ).lower()
    review_slots = {
        ReviewPlusMaterialRole.REVIEW_RULE.value,
        ReviewPlusMaterialRole.CHECKLIST.value,
        ReviewPlusMaterialRole.TASK_BOOK.value,
    }
    subject_roles = {
        ReviewPlusMaterialRole.SUBJECT_REPORT.value,
        ReviewPlusMaterialRole.SUBJECT_DOCUMENT.value,
        ReviewPlusMaterialRole.SUPPORTING_ATTACHMENT.value,
    }

    if roles & review_slots and roles & subject_roles:
        return "设计审查材料包", "质量保证"
    if recommended_route == "gnc_review":
        return "GNC 设计报告", "GNC/控制"
    if recommended_route == "review_plus":
        return "设计审查材料", "质量保证"
    if any(token in names for token in ("电机", "外框", "定子", "转子", "cmg", "同步器", "码盘")):
        return "电机/机构规格文档", "机械/电气"
    if any(token in names for token in ("报告", "方案", "设计", "分析")):
        return "设计报告", "综合"
    if len(normalized) > 1:
        return "批量材料包", "综合"
    return "单文档", "通用审查"


def _apply_review_plus_slot_override(
    *,
    recommended_route: str,
    material_roles_payload: list[dict[str, Any]],
    materials: list,
    reason: str,
) -> tuple[str, str]:
    from data_agent.super_agent.execution_plan import (
        material_roles_payload_hint_review_plus,
        materials_hint_review_plus,
    )

    slot_reason = "材料包满足文件组审查槽位（规则/检查单、任务书、被审材料），优先走文件组审查"
    if recommended_route == "review_plus":
        return recommended_route, reason
    if material_roles_payload_hint_review_plus(material_roles_payload) or materials_hint_review_plus(materials):
        return "review_plus", slot_reason
    return recommended_route, reason


def _maybe_apply_adaptive_router(
    run: SuperAgentRun,
    materials: list[dict[str, Any]],
    classification: dict[str, Any],
    slot_status: dict[str, Any],
) -> dict[str, Any]:
    from data_agent.core.adaptive_router import (
        build_router_input_from_run,
        merge_guarded_into_classification,
        route_adaptive,
    )
    from data_agent.core.config import is_adaptive_router_enabled

    if not is_adaptive_router_enabled():
        return classification
    try:
        router_input = build_router_input_from_run(
            run.objective or "",
            materials,
            classification,
            slot_status,
        )
        guarded = route_adaptive(router_input)
        return merge_guarded_into_classification(classification, guarded)
    except Exception:
        logger.exception("adaptive router failed; keeping baseline classification")
        return classification


def _recommended_route_from_classification(classification: dict[str, Any]) -> str:
    from data_agent.core.adaptive_router import adaptive_route_from_classification, execution_route_from_adaptive

    guarded = adaptive_route_from_classification(classification)
    if guarded and guarded.source != "error":
        mapped = execution_route_from_adaptive(guarded)
        if mapped:
            return mapped
    return str(classification.get("recommended_route") or "smart")


def _route_from_explicit_request(
    run: SuperAgentRun,
    route: SuperAgentRoute,
    *,
    request: CreateSuperAgentRunRequest | None = None,
) -> SuperAgentRouteDecision:
    from data_agent.super_agent.execution_plan import (
        material_roles_payload_hint_review_plus,
        materials_hint_review_plus,
    )

    materials = list(request.materials if request and request.materials else run.materials)
    classification = run.classification if isinstance(run.classification, dict) else {}
    material_roles = classification.get("material_roles") if isinstance(classification.get("material_roles"), list) else []

    if route in {SuperAgentRoute.GNC_REVIEW_ONLY, SuperAgentRoute.GNC_REVIEW}:
        if materials_hint_review_plus(materials) or material_roles_payload_hint_review_plus(material_roles):
            route = SuperAgentRoute.REVIEW_PLUS
            reasons = ["文件组槽位已闭合，纠正 GNC 路由为文件组审查。"]
            return SuperAgentRouteDecision(
                route=route,
                confidence=0.95,
                reasons=reasons,
                required_tools=tools_for_route(route),
                classification=classification if classification else {},
            )

    if route == SuperAgentRoute.REVIEW_PLUS:
        slot_status = helpers.compute_review_plus_slot_status(material_roles)
        if not slot_status["review_plus_ready"]:
            missing = "、".join(slot_status["missing_slots"])
            return SuperAgentRouteDecision(
                route=SuperAgentRoute.SMART,
                confidence=0.78,
                reasons=[
                    f"用户指定文件组审查，但材料槽位不完整（缺少 {missing}），"
                    "已降级为智能审查。"
                ],
                required_tools=tools_for_route(SuperAgentRoute.SMART),
                classification=classification if classification else {},
            )

    return SuperAgentRouteDecision(
        route=route,
        confidence=1.0,
        reasons=[f"用户显式指定 route={route.value}"],
        required_tools=tools_for_route(route),
        classification=classification if classification else {},
    )


class ClassifyAndRoutePhaseHandler(PhaseHandlerBase):
    phase_id = "classify_and_route"
    wizard_step = 2

    def __init__(self, host):
        super().__init__(host)

    def apply_wizard_checkpoint(self, run, req) -> None:
        from data_agent.super_agent.execution_plan import (
            requested_route_from_review_mode_selection,
            review_mode_selection_from_run,
        )

        if req.objective is not None:
            run.objective = req.objective
        if req.processing_mode is not None:
            run.processing_mode = req.processing_mode or "OPTIMAL"
        if req.review_mode_selection is not None:
            if not isinstance(run.classification, dict):
                run.classification = {}
            run.classification["review_mode_selection"] = req.review_mode_selection
            run.requested_route = requested_route_from_review_mode_selection(
                req.review_mode_selection,
                classification=run.classification,
            )
        elif req.requested_route is not None:
            run.requested_route = req.requested_route
            if not isinstance(run.classification, dict):
                run.classification = {}
            selection = review_mode_selection_from_run(run)
            if req.requested_route == SuperAgentRoute.REVIEW_PLUS:
                selection = "standard"
            elif req.requested_route in {SuperAgentRoute.GNC_REVIEW_ONLY, SuperAgentRoute.GNC_REVIEW}:
                selection = "specialized"
            elif req.requested_route == SuperAgentRoute.AUTO:
                selection = "smart"
            run.classification["review_mode_selection"] = selection

        if req.classification is not None:
            run.classification = req.classification
            self._attach_execution_plan_preview(run, processing_mode_override=req.processing_mode)
            advance_wizard_phase(
                run,
                "classify_and_route",
                status="completed",
                artifact=self._classify_phase_artifact(run),
            )
        elif helpers._has_saved_classification(run.classification) and (
            req.requested_route is not None
            or req.review_mode_selection is not None
            or req.processing_mode is not None
            or req.objective is not None
        ):
            self._attach_execution_plan_preview(run, processing_mode_override=req.processing_mode)
            advance_wizard_phase(
                run,
                "classify_and_route",
                status="completed",
                artifact=self._classify_phase_artifact(run),
            )

    def _classify_phase_artifact(self, run: SuperAgentRun) -> dict[str, Any]:
        classification = dict(run.classification) if isinstance(run.classification, dict) else {}
        artifact: dict[str, Any] = {"classification": classification}
        if classification.get("parse_plan"):
            artifact["parse_plan"] = classification["parse_plan"]
        if classification.get("review_plan"):
            artifact["review_plan"] = classification["review_plan"]
        if run.route_decision is not None:
            artifact["route_decision"] = run.route_decision.model_dump(mode="json")
        return artifact

    def _attach_execution_plan_preview(
        self,
        run: SuperAgentRun,
        *,
        request: CreateSuperAgentRunRequest | None = None,
        processing_mode_override: str | None = None,
    ) -> None:
        from data_agent.super_agent.execution_plan import compute_execution_plan_preview

        classification = dict(run.classification) if isinstance(run.classification, dict) else {}
        if not helpers._has_saved_classification(classification):
            return
        if request is None and hasattr(self._host, "build_execution_request"):
            request = self._host.build_execution_request(run)
        decision = self.route_review_task(run, request=request)
        parse_plan, review_plan = compute_execution_plan_preview(
            run,
            classification,
            decision,
            request=request,
            processing_mode_override=processing_mode_override,
        )
        classification["parse_plan"] = parse_plan
        classification["review_plan"] = review_plan
        run.classification = classification
        run.route_decision = decision
        if processing_mode_override is None and parse_plan.get("default_processing_mode"):
            run.processing_mode = str(parse_plan["default_processing_mode"])

    def execute_pipeline(self, ctx) -> "SuperAgentRouteDecision":
        run = ctx.run
        request = ctx.request
        resume = ctx.resume
        if resume and self._host.step_completed(run, "classify") and run.route_decision:
            decision = run.route_decision
        else:
            decision = self._host.classify_task(run, request=request)
            run.route_decision = decision
            if decision.classification:
                run.classification = decision.classification
            self._host.mark_step_completed(run, "classify")
        self._host.checkpoint_run(run)
        return decision

    def classify_run_materials(self, run_id: str) -> dict[str, Any]:
        """classify_and_route: L0/L1 classification only — persist roles and parsing tier recommendations."""
        run = self._host.get_run(run_id)
        if not run:
            raise ValueError(f"Super Agent run not found: {run_id}")
        if not run.materials and not run.source_review_id:
            raise ValueError(f"Super Agent run has no materials to classify: {run_id}")

        materials = helpers.enrich_material_previews(list(run.materials))
        classification = self.classify_materials(run, materials)
        run.classification = classification
        self._attach_execution_plan_preview(run)
        classification = dict(run.classification)
        advance_wizard_phase(
            run,
            "classify_and_route",
            status="completed",
            artifact=self._classify_phase_artifact(run),
        )
        self._host.checkpoint_run(run)
        return classification

    def classify_task(
        self,
        run: SuperAgentRun,
        *,
        request: CreateSuperAgentRunRequest | None = None,
    ) -> SuperAgentRouteDecision:
        """L1: lightweight route classification (reuses /classify + slot heuristics)."""
        return self.route_review_task(run, request=request)

    def classify_materials(
        self,
        run: SuperAgentRun,
        materials: list[SuperAgentMaterial] | list[dict[str, Any]],
    ) -> dict[str, Any]:
        """L0/L1 classification only — metadata routing, roles, parsing tier recommendations."""
        from data_agent.services.task_classifier import classify_batch

        normalized: list[dict[str, Any]] = []
        for material in materials:
            item = material.model_dump() if isinstance(material, SuperAgentMaterial) else dict(material)
            if item.get("role") and not item.get("role_hint"):
                item["role_hint"] = item.get("role")
            if item.get("name") and not item.get("file_name"):
                item["file_name"] = item.get("name")
            if item.get("filename") and not item.get("file_name"):
                item["file_name"] = item.get("filename")
            normalized.append(item)
        existing = run.classification if isinstance(run.classification, dict) else {}
        user_overrides = existing.get("user_overrides")
        if not isinstance(user_overrides, dict):
            user_overrides = None
        deterministic = classify_batch(
            normalized,
            objective=run.objective,
            user_overrides=user_overrides,
        )
        recommended_route = _CLASSIFICATION_ROUTE_MAP.get(deterministic.route, deterministic.route)
        material_roles_payload = [
            item.model_dump(mode="json") for item in deterministic.material_roles
        ]
        recommended_route, route_reason = _apply_review_plus_slot_override(
            recommended_route=recommended_route,
            material_roles_payload=material_roles_payload,
            materials=normalized,
            reason=deterministic.reason,
        )
        slot_status = helpers.compute_review_plus_slot_status(material_roles_payload)
        if recommended_route == "review_plus" and not slot_status["review_plus_ready"]:
            missing = "、".join(slot_status["missing_slots"])
            recommended_route = "smart"
            route_reason = (
                f"材料包缺少 Review-Plus 必需槽位（{missing}），"
                "已推荐智能审查；请补充规则/检查单、任务书与被审材料后再走文件组审查。"
            )
        metadata_payload = deterministic.metadata.model_dump(mode="json")
        doc_type, domain = _infer_classification_labels(
            normalized,
            material_roles_payload,
            recommended_route,
        )
        classification = helpers._build_classification_payload(
            normalized=normalized,
            material_roles=material_roles_payload,
            recommended_route=recommended_route,
            reason=route_reason,
            confidence=deterministic.confidence,
            metadata=metadata_payload,
            doc_type=doc_type,
            domain=domain,
            slot_status=slot_status,
        )
        classification["initial_recommended_route"] = recommended_route
        if user_overrides:
            classification["user_overrides"] = dict(user_overrides)
        return _maybe_apply_adaptive_router(run, normalized, classification, slot_status)

    def route_review_task(
        self,
        run: SuperAgentRun,
        *,
        request: CreateSuperAgentRunRequest | None = None,
    ) -> SuperAgentRouteDecision:
        if run.requested_route != SuperAgentRoute.AUTO:
            return _route_from_explicit_request(run, run.requested_route, request=request)

        if run.review_mode in {SuperAgentReviewMode.SINGLE_DOC, SuperAgentReviewMode.MULTI_DOC}:
            return SuperAgentRouteDecision(
                route=SuperAgentRoute.GNC_REVIEW_ONLY,
                confidence=0.9,
                reasons=[f"review_mode={run.review_mode.value}，进入 GNC 专项审查。"],
                required_tools=tools_for_route(SuperAgentRoute.GNC_REVIEW_ONLY),
                gnc_review_id=run.source_review_id if run.input_mode == SuperAgentInputMode.EXISTING_GNC_REVIEW else "",
            )

        if run.input_mode == SuperAgentInputMode.EXISTING_GNC_REVIEW:
            return SuperAgentRouteDecision(
                route=SuperAgentRoute.GNC_REVIEW_ONLY,
                confidence=0.95,
                reasons=["输入模式为 existing_gnc_review，委托 GNC 评审链路（Phase 5 实现）。"],
                required_tools=tools_for_route(SuperAgentRoute.GNC_REVIEW_ONLY),
                gnc_review_id=run.source_review_id,
            )

        is_upload = run.input_mode == SuperAgentInputMode.UPLOAD or (
            request is not None and request.input_mode == SuperAgentInputMode.UPLOAD
        )
        if is_upload:
            materials = request.materials if request else run.materials
            if not materials:
                return SuperAgentRouteDecision(
                    route=SuperAgentRoute.STRUCTURE_ONLY,
                    confidence=0.45,
                    reasons=["上传模式尚未携带可执行材料，先进入结构化能力。"],
                    required_tools=tools_for_route(SuperAgentRoute.STRUCTURE_ONLY),
                )
            if run.requested_route == SuperAgentRoute.AUTO and not run.source_review_id:
                materials = helpers.enrich_material_previews(list(materials))
                if helpers._has_saved_classification(run.classification):
                    classification = dict(run.classification)
                else:
                    classification = self.classify_materials(run, materials)
                recommended = _recommended_route_from_classification(classification)
                chosen_route = _EXECUTION_ROUTE_MAP.get(recommended, SuperAgentRoute.SMART)
                slot_status = helpers.compute_review_plus_slot_status(
                    classification.get("material_roles") if isinstance(classification.get("material_roles"), list) else []
                )
                if chosen_route == SuperAgentRoute.REVIEW_PLUS and not slot_status["review_plus_ready"]:
                    chosen_route = SuperAgentRoute.SMART
                return SuperAgentRouteDecision(
                    route=chosen_route,
                    confidence=0.85,
                    reasons=[
                        f"自动识别: {classification.get('doc_type', '未知')}, "
                        f"领域: {classification.get('domain', '未知')}. "
                        f"{classification.get('reason', '')}"
                    ],
                    required_tools=tools_for_route(chosen_route),
                    classification=classification,
                )

        if run.source_review_id:
            from data_agent.review_plus.service import get_review_plus_service

            task = get_review_plus_service().get_review(run.source_review_id)
            if task:
                roles = {helpers._role_value(getattr(material, "role", "")) for material in task.materials}
                has_rule = bool({"review_rule", "checklist"} & roles)
                has_task = "task_book" in roles
                has_subject = bool({"subject_report", "subject_document", "supporting_attachment"} & roles)
                if has_rule and has_task and has_subject:
                    return SuperAgentRouteDecision(
                        route=SuperAgentRoute.REVIEW_PLUS,
                        confidence=0.92,
                        reasons=["材料包满足 Review-Plus 槽位：规则/检查单、任务书、被审材料均存在。"],
                        required_tools=tools_for_route(SuperAgentRoute.REVIEW_PLUS),
                    )
                return SuperAgentRouteDecision(
                    route=SuperAgentRoute.STRUCTURE_ONLY,
                    confidence=0.62,
                    reasons=["找到 Review-Plus 任务，但材料槽位未完整闭合，先进行结构化与质量报告。"],
                    required_tools=tools_for_route(SuperAgentRoute.STRUCTURE_ONLY),
                    skipped_tools=["run_review_plus"],
                )

        return SuperAgentRouteDecision(
            route=SuperAgentRoute.STRUCTURE_ONLY,
            confidence=0.5,
            reasons=["未识别到可委托的现有 Review-Plus/GNC 任务。"],
            required_tools=tools_for_route(SuperAgentRoute.STRUCTURE_ONLY),
        )