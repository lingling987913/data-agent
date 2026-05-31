"""Domain registry: specialists, skills, harness mapping, and route signals."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from data_agent.review_plus.agent_harness import SPECIALIST_TO_HARNESS_AGENT as _FALLBACK_HARNESS
from data_agent.review_plus.specialist_orchestration_service import SPECIALIST_CATALOG as _FALLBACK_CATALOG

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DOMAINS_DIR = _PROJECT_ROOT / "config" / "domains"
_DEFAULT_DOMAIN_ID = "aerospace_review"

_FALLBACK_SKILL_REFS: dict[str, str] = {
    "document_format_reviewer": "review-plus/document-format",
    "requirements_traceability_reviewer": "review-plus/technical-consistency",
    "product_assurance_reviewer": "review-plus/product-assurance",
    "reliability_safety_reviewer": "review-plus/reliability-safety",
    "gnc_design_reviewer": "review-plus/gnc-design",
    "attitude_control_reviewer": "review-plus/attitude-control",
    "attitude_determination_reviewer": "review-plus/attitude-determination",
    "verification_reviewer": "review-plus/verification",
    "interface_reviewer": "review-plus/interface-consistency",
}

_FALLBACK_SPECIALIST_DOMAINS: dict[str, str] = {
    "document_format_reviewer": "文档格式",
    "requirements_traceability_reviewer": "需求追溯",
    "product_assurance_reviewer": "产品保证",
    "reliability_safety_reviewer": "可靠性安全性",
    "gnc_design_reviewer": "GNC/控制",
    "attitude_control_reviewer": "姿态控制",
    "attitude_determination_reviewer": "姿态确定",
    "verification_reviewer": "验证",
    "interface_reviewer": "接口一致性",
}

_FALLBACK_ROUTE_SIGNALS: dict[str, list[str]] = {
    "gnc_strong": ["gnc", "姿态", "轨控", "卫星", "飞轮", "星敏", "陀螺"],
    "gnc_weak": ["导航", "控制"],
}


_AEROSPACE_DOMAIN_HINTS = (
    "aerospace",
    "aerospace_review",
    "航天",
    "卫星",
    "gnc",
    "飞轮",
    "轨控",
    "星敏",
    "陀螺",
    "姿态控制",
)
_GENERIC_DOMAIN_HINTS = (
    "generic_document_review",
    "generic",
    "通用审查",
    "通用文档",
    "文档审查",
    "验收报告",
    "合同",
    "方案审查",
    "机械/电气",
    "机械",
    "电气",
    "电机",
    "机构",
    "规格文档",
    "电机/机构规格文档",
    "外框",
    "定子",
    "转子",
)


@dataclass
class DomainProfile:
    domain_id: str
    display_name: str
    specialists: dict[str, dict[str, Any]] = field(default_factory=dict)
    skill_refs: dict[str, str] = field(default_factory=dict)
    harness_agents: dict[str, str] = field(default_factory=dict)
    route_signals: dict[str, list[str]] = field(default_factory=dict)
    specialist_domains: dict[str, str] = field(default_factory=dict)
    committee_defaults: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain_id": self.domain_id,
            "display_name": self.display_name,
            "specialists": dict(self.specialists),
            "skill_refs": dict(self.skill_refs),
            "harness_agents": dict(self.harness_agents),
            "route_signals": dict(self.route_signals),
            "specialist_domains": dict(self.specialist_domains),
            "committee_defaults": dict(self.committee_defaults),
        }


def _build_fallback_profile(domain_id: str = _DEFAULT_DOMAIN_ID) -> DomainProfile:
    return DomainProfile(
        domain_id=domain_id,
        display_name="航天设计审查",
        specialists={key: dict(value) for key, value in _FALLBACK_CATALOG.items()},
        skill_refs=dict(_FALLBACK_SKILL_REFS),
        harness_agents=dict(_FALLBACK_HARNESS),
        route_signals={key: list(value) for key, value in _FALLBACK_ROUTE_SIGNALS.items()},
        specialist_domains=dict(_FALLBACK_SPECIALIST_DOMAINS),
    )


def _profile_from_payload(payload: dict[str, Any], domain_id: str) -> DomainProfile:
    route_signals = {
        str(key): [str(item) for item in values]
        for key, values in (payload.get("route_signals") or {}).items()
        if isinstance(values, list)
    }
    return DomainProfile(
        domain_id=str(payload.get("domain_id") or domain_id),
        display_name=str(payload.get("display_name") or domain_id),
        specialists={
            str(key): dict(value)
            for key, value in (payload.get("specialists") or {}).items()
            if isinstance(value, dict)
        },
        skill_refs={
            str(key): str(value)
            for key, value in (payload.get("skill_refs") or {}).items()
        },
        harness_agents={
            str(key): str(value)
            for key, value in (payload.get("harness_agents") or {}).items()
        },
        route_signals=route_signals or {key: list(value) for key, value in _FALLBACK_ROUTE_SIGNALS.items()},
        specialist_domains={
            str(key): str(value)
            for key, value in (payload.get("specialist_domains") or {}).items()
        },
        committee_defaults={
            str(key): value
            for key, value in (payload.get("committee_defaults") or {}).items()
        },
    )


@lru_cache(maxsize=8)
def load_domain_profile(domain_id: str = _DEFAULT_DOMAIN_ID) -> DomainProfile:
    """Load a domain profile from JSON, falling back to embedded Python constants."""
    path = _DOMAINS_DIR / f"{domain_id}.json"
    if not path.is_file():
        if domain_id == _DEFAULT_DOMAIN_ID:
            return _build_fallback_profile(domain_id)
        raise KeyError(f"unknown domain_id: {domain_id}")
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        return _build_fallback_profile(domain_id)
    profile = _profile_from_payload(payload, domain_id)
    if domain_id == _DEFAULT_DOMAIN_ID:
        if not profile.specialists:
            profile.specialists = {key: dict(value) for key, value in _FALLBACK_CATALOG.items()}
        if not profile.harness_agents:
            profile.harness_agents = dict(_FALLBACK_HARNESS)
        if not profile.skill_refs:
            profile.skill_refs = dict(_FALLBACK_SKILL_REFS)
        if not profile.specialist_domains:
            profile.specialist_domains = dict(_FALLBACK_SPECIALIST_DOMAINS)
    return profile


def default_domain_profile() -> DomainProfile:
    return load_domain_profile(_DEFAULT_DOMAIN_ID)


def specialist_catalog_for_domain(domain_id: str = _DEFAULT_DOMAIN_ID) -> dict[str, dict[str, Any]]:
    return dict(load_domain_profile(domain_id).specialists)


def harness_agent_for_specialist(specialist_id: str, domain_id: str = _DEFAULT_DOMAIN_ID) -> str | None:
    return load_domain_profile(domain_id).harness_agents.get(specialist_id)


def route_signals_for_domain(domain_id: str = _DEFAULT_DOMAIN_ID) -> dict[str, list[str]]:
    profile = load_domain_profile(domain_id)
    return {key: list(values) for key, values in profile.route_signals.items()}


def _contains_domain_hint(text: str, hints: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(hint.lower() in lowered for hint in hints)


def resolve_domain_id(
    classification: dict[str, Any] | None = None,
    *,
    objective: str = "",
    doc_type: str = "",
) -> str:
    if not isinstance(classification, dict):
        return _DEFAULT_DOMAIN_ID
    explicit = str(classification.get("domain_id") or "").strip()
    if explicit:
        return explicit

    domain_label = str(classification.get("domain") or "").strip()
    doc_type_label = str(classification.get("doc_type") or doc_type or "").strip()
    objective_text = str(classification.get("objective") or objective or "").strip()
    combined = " ".join(part for part in (domain_label, doc_type_label, objective_text) if part)

    if _contains_domain_hint(combined, _AEROSPACE_DOMAIN_HINTS):
        return _DEFAULT_DOMAIN_ID
    if domain_label.lower() in {"gnc/控制", "gnc", "航天设计审查", "aerospace_review"}:
        return _DEFAULT_DOMAIN_ID

    if _contains_domain_hint(combined, _GENERIC_DOMAIN_HINTS):
        return "generic_document_review"
    if domain_label in {"通用审查", "通用文档审查"}:
        return "generic_document_review"

    return "generic_document_review"


def committee_defaults_for_domain(domain_id: str = _DEFAULT_DOMAIN_ID) -> dict[str, Any]:
    return dict(load_domain_profile(domain_id).committee_defaults)


def review_units_for_domain(
    domain_id: str = _DEFAULT_DOMAIN_ID,
    *,
    group: str | None = None,
) -> dict[str, dict[str, Any]]:
    """Return specialist entries that are professional review units (AD/AC).

    Review units are specialists carrying a ``unit_group`` marker. Plain
    specialists (the legacy 9 reviewers) are excluded. Optionally filter by
    ``group`` ("ad"/"ac"); results are ordered by ``unit_order`` then id.
    """
    profile = load_domain_profile(domain_id)
    units: list[tuple[str, dict[str, Any]]] = []
    for specialist_id, payload in profile.specialists.items():
        unit_group = str(payload.get("unit_group") or "").strip().lower()
        if not unit_group:
            continue
        if group is not None and unit_group != str(group).strip().lower():
            continue
        units.append((specialist_id, dict(payload)))

    def _order_key(item: tuple[str, dict[str, Any]]) -> tuple[str, int, str]:
        specialist_id, payload = item
        unit_group = str(payload.get("unit_group") or "")
        try:
            order = int(payload.get("unit_order", 0))
        except (TypeError, ValueError):
            order = 0
        return (unit_group, order, specialist_id)

    units.sort(key=_order_key)
    return {specialist_id: payload for specialist_id, payload in units}


__all__ = [
    "DomainProfile",
    "committee_defaults_for_domain",
    "default_domain_profile",
    "harness_agent_for_specialist",
    "load_domain_profile",
    "resolve_domain_id",
    "review_units_for_domain",
    "route_signals_for_domain",
    "specialist_catalog_for_domain",
]
