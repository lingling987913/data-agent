"""Adaptive Router: LLM-auxiliary routing with deterministic guardrails (Hermes P9/P10)."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal

from data_agent.core.config import is_adaptive_router_enabled
from data_agent.core.domain_registry import (
    _AEROSPACE_DOMAIN_HINTS,
    load_domain_profile,
    resolve_domain_id,
    route_signals_for_domain,
    specialist_catalog_for_domain,
)
from data_agent.core.task_spec import task_spec_from_dict, task_specs_from_dicts

logger = logging.getLogger(__name__)

CONFIDENCE_THRESHOLD = 0.55

_ADAPTIVE_ROUTE_VALUES = frozenset({"review_plus", "gnc_review", "smart", "structure_only"})
_PRIMARY_PATH_VALUES = frozenset({"review_plus", "gnc", "smart_committee", "structure_only"})
_KNOWN_DOMAIN_IDS = frozenset({"aerospace_review", "generic_document_review"})

_MECHANICAL_ELECTRICAL_TOKENS = (
    "机械",
    "电气",
    "电机",
    "机构",
    "规格",
    "外框",
    "定子",
    "转子",
    "cmg",
    "同步器",
    "码盘",
)


class AdaptiveRoute(str, Enum):
    REVIEW_PLUS = "review_plus"
    GNC_REVIEW = "gnc_review"
    SMART = "smart"
    STRUCTURE_ONLY = "structure_only"


class AdaptivePrimaryPath(str, Enum):
    REVIEW_PLUS = "review_plus"
    GNC = "gnc"
    SMART_COMMITTEE = "smart_committee"
    STRUCTURE_ONLY = "structure_only"


@dataclass
class DocSummary:
    file_name: str
    role: str = ""
    doc_type_hint: str = ""
    content_preview: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "file_name": self.file_name,
            "role": self.role,
            "doc_type_hint": self.doc_type_hint,
            "content_preview": self.content_preview[:500],
        }


@dataclass
class DomainCatalogEntry:
    domain_id: str
    display_name: str
    specialist_ids: list[str] = field(default_factory=list)
    route_signals: dict[str, list[str]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain_id": self.domain_id,
            "display_name": self.display_name,
            "specialist_ids": list(self.specialist_ids),
            "route_signals": {key: list(values) for key, values in self.route_signals.items()},
        }


@dataclass
class SelectedCapabilities:
    primary_path: str = "smart_committee"
    specialist_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "primary_path": self.primary_path,
            "specialist_ids": list(self.specialist_ids),
        }


@dataclass
class AdaptiveRouterInput:
    objective: str = ""
    doc_summaries: list[DocSummary] = field(default_factory=list)
    material_roles: list[dict[str, Any]] = field(default_factory=list)
    slot_status: dict[str, Any] = field(default_factory=dict)
    domain_catalog: list[DomainCatalogEntry] = field(default_factory=list)
    available_routes: list[str] = field(default_factory=list)
    baseline_classification: dict[str, Any] = field(default_factory=dict)
    user_overrides: dict[str, Any] = field(default_factory=dict)

    def corpus_text(self) -> str:
        parts = [self.objective]
        for doc in self.doc_summaries:
            parts.extend([doc.file_name, doc.doc_type_hint, doc.content_preview])
        for item in self.material_roles:
            if isinstance(item, dict):
                parts.append(str(item.get("file_name") or item.get("filename") or ""))
                parts.append(str(item.get("content_preview") or "")[:300])
        baseline = self.baseline_classification
        parts.extend(
            [
                str(baseline.get("domain") or ""),
                str(baseline.get("doc_type") or ""),
                str(baseline.get("reason") or ""),
            ]
        )
        return " ".join(part for part in parts if part).lower()


@dataclass
class AdaptiveRouterDecision:
    domain_id: str = "generic_document_review"
    route: str = "smart"
    confidence: float = 0.0
    reasoning_summary: str = ""
    selected_capabilities: SelectedCapabilities = field(default_factory=SelectedCapabilities)
    task_specs: list[dict[str, Any]] = field(default_factory=list)
    missing_info: list[str] = field(default_factory=list)
    risk_flags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain_id": self.domain_id,
            "route": self.route,
            "confidence": self.confidence,
            "reasoning_summary": self.reasoning_summary,
            "selected_capabilities": self.selected_capabilities.to_dict(),
            "task_specs": list(self.task_specs),
            "missing_info": list(self.missing_info),
            "risk_flags": list(self.risk_flags),
        }


@dataclass
class GuardedRouterDecision:
    source: Literal["baseline", "llm", "error"] = "baseline"
    domain_id: str = "generic_document_review"
    route: str = "smart"
    primary_path: str = "smart_committee"
    confidence: float = 0.0
    reasoning_summary: str = ""
    selected_capabilities: SelectedCapabilities = field(default_factory=SelectedCapabilities)
    task_specs: list[dict[str, Any]] = field(default_factory=list)
    missing_info: list[str] = field(default_factory=list)
    risk_flags: list[str] = field(default_factory=list)
    guardrail_corrections: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "domain_id": self.domain_id,
            "route": self.route,
            "primary_path": self.primary_path,
            "confidence": self.confidence,
            "reasoning_summary": self.reasoning_summary,
            "selected_capabilities": self.selected_capabilities.to_dict(),
            "task_specs": list(self.task_specs),
            "missing_info": list(self.missing_info),
            "risk_flags": list(self.risk_flags),
            "guardrail_corrections": list(self.guardrail_corrections),
        }


def _route_to_primary_path(route: str) -> str:
    mapping = {
        "review_plus": "review_plus",
        "gnc_review": "gnc",
        "smart": "smart_committee",
        "structure_only": "structure_only",
    }
    return mapping.get(str(route or "").strip().lower(), "smart_committee")


def _primary_path_to_route(primary_path: str) -> str:
    mapping = {
        "review_plus": "review_plus",
        "gnc": "gnc_review",
        "smart_committee": "smart",
        "structure_only": "structure_only",
    }
    return mapping.get(str(primary_path or "").strip().lower(), "smart")


def _classification_recommended_route(route: str) -> str:
    normalized = str(route or "").strip().lower()
    if normalized == "structure_only":
        return "smart"
    return normalized if normalized in {"review_plus", "gnc_review", "smart"} else "smart"


def build_domain_catalog() -> list[DomainCatalogEntry]:
    catalog: list[DomainCatalogEntry] = []
    for domain_id in sorted(_KNOWN_DOMAIN_IDS):
        try:
            profile = load_domain_profile(domain_id)
        except KeyError:
            continue
        catalog.append(
            DomainCatalogEntry(
                domain_id=profile.domain_id,
                display_name=profile.display_name,
                specialist_ids=sorted(profile.specialists.keys()),
                route_signals=dict(profile.route_signals),
            )
        )
    return catalog


def build_router_input_from_run(
    objective: str,
    materials: list[dict[str, Any]] | None,
    classification: dict[str, Any] | None,
    slot_status: dict[str, Any] | None,
) -> AdaptiveRouterInput:
    baseline = dict(classification) if isinstance(classification, dict) else {}
    roles = baseline.get("material_roles") if isinstance(baseline.get("material_roles"), list) else []
    if not roles and materials:
        roles = [dict(item) for item in materials if isinstance(item, dict)]

    doc_summaries: list[DocSummary] = []
    for item in roles:
        if not isinstance(item, dict):
            continue
        doc_summaries.append(
            DocSummary(
                file_name=str(item.get("file_name") or item.get("filename") or item.get("name") or ""),
                role=str(item.get("role") or ""),
                doc_type_hint=str(item.get("doc_type") or baseline.get("doc_type") or ""),
                content_preview=str(item.get("content_preview") or item.get("content") or "")[:500],
            )
        )

    overrides = {}
    if isinstance(baseline.get("user_overrides"), dict):
        overrides = dict(baseline["user_overrides"])
    review_mode = baseline.get("review_mode_selection")
    if review_mode:
        overrides.setdefault("review_mode_selection", review_mode)

    return AdaptiveRouterInput(
        objective=str(objective or baseline.get("objective") or ""),
        doc_summaries=doc_summaries,
        material_roles=[dict(item) for item in roles if isinstance(item, dict)],
        slot_status=dict(slot_status or {}),
        domain_catalog=build_domain_catalog(),
        available_routes=sorted(_ADAPTIVE_ROUTE_VALUES),
        baseline_classification=baseline,
        user_overrides=overrides,
    )


def baseline_guarded_decision(inp: AdaptiveRouterInput) -> GuardedRouterDecision:
    baseline = inp.baseline_classification
    route = str(baseline.get("recommended_route") or "smart").strip().lower()
    if route not in _ADAPTIVE_ROUTE_VALUES:
        route = "smart"
    domain_id = resolve_domain_id(baseline, objective=inp.objective)
    primary_path = _route_to_primary_path(route)
    confidence = float(baseline.get("confidence") or 0.65)
    reasoning = str(baseline.get("reason") or "baseline rule classification")
    return GuardedRouterDecision(
        source="baseline",
        domain_id=domain_id,
        route=route,
        primary_path=primary_path,
        confidence=confidence,
        reasoning_summary=reasoning,
        selected_capabilities=SelectedCapabilities(primary_path=primary_path),
    )


def _contains_hint(text: str, hints: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(hint.lower() in lowered for hint in hints)


def _has_mechanical_electrical_signal(corpus: str) -> bool:
    return any(token in corpus for token in _MECHANICAL_ELECTRICAL_TOKENS)


def _has_aerospace_strong_signal(corpus: str, domain_id: str = "aerospace_review") -> bool:
    signals = route_signals_for_domain(domain_id)
    strong = tuple(signals.get("gnc_strong") or ()) + _AEROSPACE_DOMAIN_HINTS
    return _contains_hint(corpus, strong)


def _has_gnc_strong_signal(corpus: str, domain_id: str = "aerospace_review") -> bool:
    signals = route_signals_for_domain(domain_id)
    strong = tuple(signals.get("gnc_strong") or ())
    return any(token.lower() in corpus for token in strong)


def _has_gnc_weak_only_signal(corpus: str, domain_id: str = "aerospace_review") -> bool:
    signals = route_signals_for_domain(domain_id)
    weak = tuple(signals.get("gnc_weak") or ())
    has_weak = any(token.lower() in corpus for token in weak)
    return has_weak and not _has_gnc_strong_signal(corpus, domain_id)


def _valid_specialists_for_domain(domain_id: str, specialist_ids: list[str]) -> list[str]:
    catalog = specialist_catalog_for_domain(domain_id)
    return [item for item in specialist_ids if item in catalog]


def _parse_task_specs(payload: list[Any] | None, domain_id: str) -> list[dict[str, Any]]:
    specs = task_specs_from_dicts(payload)
    valid_specialists = set(specialist_catalog_for_domain(domain_id))
    result: list[dict[str, Any]] = []
    for spec in specs:
        if not spec.task_id or not spec.specialist_id:
            continue
        if spec.specialist_id not in valid_specialists:
            continue
        try:
            task_spec_from_dict(spec.to_dict())
        except (TypeError, ValueError):
            continue
        item = spec.to_dict()
        input_summary = dict(item.get("input_summary") or {})
        input_summary.setdefault("domain_id", domain_id)
        item["input_summary"] = input_summary
        result.append(item)
    return result


def apply_guardrails(
    llm_decision: AdaptiveRouterDecision | GuardedRouterDecision,
    inp: AdaptiveRouterInput,
    baseline_decision: GuardedRouterDecision,
) -> GuardedRouterDecision:
    corrections: list[str] = list(getattr(llm_decision, "guardrail_corrections", None) or [])
    risk_flags = list(llm_decision.risk_flags)

    domain_id = str(llm_decision.domain_id or "").strip()
    route = str(llm_decision.route or "smart").strip().lower()
    primary_path = str(
        llm_decision.selected_capabilities.primary_path or _route_to_primary_path(route)
    ).strip().lower()
    corpus = inp.corpus_text()
    review_plus_ready = bool(inp.slot_status.get("review_plus_ready"))
    overrides = inp.user_overrides or {}

    override_domain = str(overrides.get("domain_id") or "").strip()
    override_route = str(overrides.get("route") or overrides.get("recommended_route") or "").strip().lower()
    if override_domain in _KNOWN_DOMAIN_IDS:
        if domain_id != override_domain:
            corrections.append(f"用户 override domain_id={override_domain}")
        domain_id = override_domain
    if override_route in _ADAPTIVE_ROUTE_VALUES:
        if route != override_route:
            corrections.append(f"用户 override route={override_route}")
        route = override_route
        primary_path = _route_to_primary_path(route)

    if domain_id not in _KNOWN_DOMAIN_IDS:
        corrections.append(f"domain_id={domain_id or 'empty'} 不在 registry，回退 baseline")
        return GuardedRouterDecision(
            source="baseline",
            domain_id=baseline_decision.domain_id,
            route=baseline_decision.route,
            primary_path=baseline_decision.primary_path,
            confidence=baseline_decision.confidence,
            reasoning_summary=baseline_decision.reasoning_summary,
            selected_capabilities=SelectedCapabilities(
                primary_path=baseline_decision.primary_path,
                specialist_ids=list(baseline_decision.selected_capabilities.specialist_ids),
            ),
            task_specs=list(baseline_decision.task_specs),
            missing_info=list(llm_decision.missing_info),
            risk_flags=risk_flags + ["invalid_domain_id"],
            guardrail_corrections=corrections,
        )

    if route not in _ADAPTIVE_ROUTE_VALUES:
        corrections.append(f"route={route} 非法，改为 smart")
        route = "smart"

    if primary_path not in _PRIMARY_PATH_VALUES:
        corrections.append(f"primary_path={primary_path} 非法，改为 {_route_to_primary_path(route)}")
        primary_path = _route_to_primary_path(route)

    if domain_id == "aerospace_review" and _has_mechanical_electrical_signal(corpus) and not _has_aerospace_strong_signal(corpus):
        corrections.append("机械/电气文档且无强航天信号，aerospace → generic_document_review")
        domain_id = "generic_document_review"
        if route == "gnc_review":
            route = "smart"
            primary_path = "smart_committee"

    if route == "gnc_review" and _has_gnc_weak_only_signal(corpus):
        corrections.append("仅弱 GNC 信号（控制/导航），禁止 gnc_review → smart")
        route = "smart"
        primary_path = "smart_committee"

    if route == "review_plus" and not review_plus_ready:
        corrections.append("Review-Plus 槽位未闭合，review_plus → smart")
        route = "smart"
        primary_path = "smart_committee"

    specialist_ids = _valid_specialists_for_domain(domain_id, list(llm_decision.selected_capabilities.specialist_ids))
    dropped = set(llm_decision.selected_capabilities.specialist_ids) - set(specialist_ids)
    if dropped:
        corrections.append(f"剔除非法 specialist: {', '.join(sorted(dropped))}")

    confidence = float(llm_decision.confidence or 0.0)
    if confidence < CONFIDENCE_THRESHOLD:
        corrections.append(f"confidence={confidence:.2f} 低于阈值 {CONFIDENCE_THRESHOLD}，回退 baseline")
        risk_flags.append("low_confidence")
        return GuardedRouterDecision(
            source="baseline",
            domain_id=baseline_decision.domain_id,
            route=baseline_decision.route,
            primary_path=baseline_decision.primary_path,
            confidence=baseline_decision.confidence,
            reasoning_summary=baseline_decision.reasoning_summary,
            selected_capabilities=SelectedCapabilities(
                primary_path=baseline_decision.primary_path,
                specialist_ids=list(baseline_decision.selected_capabilities.specialist_ids),
            ),
            task_specs=list(baseline_decision.task_specs),
            missing_info=list(llm_decision.missing_info),
            risk_flags=risk_flags,
            guardrail_corrections=corrections,
        )

    task_specs = _parse_task_specs(llm_decision.task_specs, domain_id)

    reasoning = str(llm_decision.reasoning_summary or baseline_decision.reasoning_summary)
    if corrections:
        reasoning = f"{reasoning} [guardrail: {'; '.join(corrections)}]"

    return GuardedRouterDecision(
        source="llm",
        domain_id=domain_id,
        route=route,
        primary_path=primary_path,
        confidence=confidence,
        reasoning_summary=reasoning,
        selected_capabilities=SelectedCapabilities(primary_path=primary_path, specialist_ids=specialist_ids),
        task_specs=task_specs,
        missing_info=list(llm_decision.missing_info),
        risk_flags=risk_flags,
        guardrail_corrections=corrections,
    )


_ROUTER_SYSTEM_PROMPT = """你是审查任务路由助手。根据用户目标、文档概况、材料角色、槽位状态、领域目录与可用路由，输出严格 JSON（不要 markdown 代码块）。

JSON 字段：
{
  "domain_id": "aerospace_review | generic_document_review",
  "route": "review_plus | gnc_review | smart | structure_only",
  "confidence": 0.0-1.0,
  "reasoning_summary": "简短中文理由",
  "selected_capabilities": {
    "primary_path": "review_plus | gnc | smart_committee | structure_only",
    "specialist_ids": ["闭集 specialist_id"]
  },
  "task_specs": [],
  "missing_info": [],
  "risk_flags": []
}

规则提示：
- review_plus 仅当槽位 review_plus_ready=true
- gnc_review 需 GNC/卫星/姿态/轨控/星敏/陀螺等强信号
- 机械/电气/电机/机构规格文档优先 generic_document_review + smart
- specialist_ids 必须来自所选 domain 的 specialist 列表
"""


def _build_router_user_prompt(inp: AdaptiveRouterInput) -> str:
    payload = {
        "objective": inp.objective,
        "doc_summaries": [doc.to_dict() for doc in inp.doc_summaries],
        "material_roles": inp.material_roles,
        "slot_status": inp.slot_status,
        "domain_catalog": [entry.to_dict() for entry in inp.domain_catalog],
        "available_routes": inp.available_routes,
        "baseline_classification": {
            "recommended_route": inp.baseline_classification.get("recommended_route"),
            "domain": inp.baseline_classification.get("domain"),
            "doc_type": inp.baseline_classification.get("doc_type"),
            "reason": inp.baseline_classification.get("reason"),
            "confidence": inp.baseline_classification.get("confidence"),
        },
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _extract_json_object(text: str) -> dict[str, Any] | None:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        parsed = json.loads(cleaned)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", cleaned)
        if not match:
            return None
        try:
            parsed = json.loads(match.group(0))
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None


def _parse_llm_decision(payload: dict[str, Any]) -> AdaptiveRouterDecision:
    caps_raw = payload.get("selected_capabilities") if isinstance(payload.get("selected_capabilities"), dict) else {}
    caps = SelectedCapabilities(
        primary_path=str(caps_raw.get("primary_path") or "smart_committee"),
        specialist_ids=[str(item) for item in caps_raw.get("specialist_ids") or [] if item],
    )
    return AdaptiveRouterDecision(
        domain_id=str(payload.get("domain_id") or "generic_document_review"),
        route=str(payload.get("route") or "smart"),
        confidence=float(payload.get("confidence") or 0.0),
        reasoning_summary=str(payload.get("reasoning_summary") or ""),
        selected_capabilities=caps,
        task_specs=[dict(item) for item in payload.get("task_specs") or [] if isinstance(item, dict)],
        missing_info=[str(item) for item in payload.get("missing_info") or []],
        risk_flags=[str(item) for item in payload.get("risk_flags") or []],
    )


def _call_router_llm(inp: AdaptiveRouterInput, llm_client: Any) -> AdaptiveRouterDecision:
    user_prompt = _build_router_user_prompt(inp)
    raw = llm_client.complete(system=_ROUTER_SYSTEM_PROMPT, user=user_prompt)
    payload = _extract_json_object(raw)
    if not payload:
        raise ValueError("router LLM response is not valid JSON")
    return _parse_llm_decision(payload)


def route_adaptive(inp: AdaptiveRouterInput, llm_client: Any | None = None) -> GuardedRouterDecision:
    """LLM-auxiliary routing with deterministic guardrails; falls back to baseline when disabled."""
    baseline = baseline_guarded_decision(inp)
    if not is_adaptive_router_enabled():
        return baseline

    if llm_client is None:
        try:
            from data_agent.core.generic_harness_runner import get_generic_llm_client

            llm_client = get_generic_llm_client()
        except Exception:
            llm_client = None

    if llm_client is None:
        return GuardedRouterDecision(
            source="baseline",
            domain_id=baseline.domain_id,
            route=baseline.route,
            primary_path=baseline.primary_path,
            confidence=baseline.confidence,
            reasoning_summary=baseline.reasoning_summary,
            selected_capabilities=SelectedCapabilities(primary_path=baseline.primary_path),
            risk_flags=["llm_unavailable"],
            guardrail_corrections=["ADAPTIVE_ROUTER_ENABLED 但 LLM 不可用，使用 baseline"],
        )

    try:
        llm_decision = _call_router_llm(inp, llm_client)
    except Exception as exc:
        logger.warning("adaptive router LLM failed: %s", exc)
        return GuardedRouterDecision(
            source="baseline",
            domain_id=baseline.domain_id,
            route=baseline.route,
            primary_path=baseline.primary_path,
            confidence=baseline.confidence,
            reasoning_summary=baseline.reasoning_summary,
            selected_capabilities=SelectedCapabilities(primary_path=baseline.primary_path),
            risk_flags=["llm_parse_failed"],
            guardrail_corrections=[f"LLM 解析失败: {exc}"],
        )

    guarded = apply_guardrails(llm_decision, inp, baseline)
    guarded.source = "llm" if guarded.source != "baseline" else "baseline"
    return guarded


def merge_guarded_into_classification(
    classification: dict[str, Any],
    guarded: GuardedRouterDecision,
) -> dict[str, Any]:
    """Merge guarded adaptive router decision into classification payload."""
    payload = dict(classification)
    payload["adaptive_router"] = guarded.to_dict()
    payload["domain_id"] = guarded.domain_id
    payload["recommended_route"] = _classification_recommended_route(guarded.route)
    base_reason = str(payload.get("reason") or "")
    router_reason = guarded.reasoning_summary
    if guarded.guardrail_corrections:
        router_reason = f"{router_reason} ({'; '.join(guarded.guardrail_corrections)})"
    payload["reason"] = router_reason or base_reason
    if guarded.confidence:
        payload["confidence"] = guarded.confidence
    return payload


def adaptive_route_from_classification(classification: dict[str, Any] | None) -> GuardedRouterDecision | None:
    if not isinstance(classification, dict):
        return None
    raw = classification.get("adaptive_router")
    if not isinstance(raw, dict) or not raw.get("source"):
        return None
    caps_raw = raw.get("selected_capabilities") if isinstance(raw.get("selected_capabilities"), dict) else {}
    return GuardedRouterDecision(
        source=str(raw.get("source") or "baseline"),  # type: ignore[arg-type]
        domain_id=str(raw.get("domain_id") or "generic_document_review"),
        route=str(raw.get("route") or "smart"),
        primary_path=str(raw.get("primary_path") or _route_to_primary_path(str(raw.get("route") or "smart"))),
        confidence=float(raw.get("confidence") or 0.0),
        reasoning_summary=str(raw.get("reasoning_summary") or ""),
        selected_capabilities=SelectedCapabilities(
            primary_path=str(caps_raw.get("primary_path") or raw.get("primary_path") or "smart_committee"),
            specialist_ids=[str(item) for item in caps_raw.get("specialist_ids") or [] if item],
        ),
        task_specs=[dict(item) for item in raw.get("task_specs") or [] if isinstance(item, dict)],
        missing_info=[str(item) for item in raw.get("missing_info") or []],
        risk_flags=[str(item) for item in raw.get("risk_flags") or []],
        guardrail_corrections=[str(item) for item in raw.get("guardrail_corrections") or []],
    )


def execution_route_from_adaptive(guarded: GuardedRouterDecision) -> str | None:
    """Map guarded adaptive route to classification recommended_route when valid."""
    if guarded.source == "error":
        return None
    route = str(guarded.route or "").strip().lower()
    if route not in _ADAPTIVE_ROUTE_VALUES:
        return None
    return _classification_recommended_route(route)


__all__ = [
    "AdaptivePrimaryPath",
    "AdaptiveRoute",
    "AdaptiveRouterDecision",
    "AdaptiveRouterInput",
    "DocSummary",
    "DomainCatalogEntry",
    "GuardedRouterDecision",
    "SelectedCapabilities",
    "adaptive_route_from_classification",
    "apply_guardrails",
    "baseline_guarded_decision",
    "build_domain_catalog",
    "build_router_input_from_run",
    "execution_route_from_adaptive",
    "merge_guarded_into_classification",
    "route_adaptive",
]
