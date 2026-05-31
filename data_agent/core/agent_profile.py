"""Lightweight agent profile registry for SMART committee specialists."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from data_agent.core.domain_registry import (
    default_domain_profile,
    harness_agent_for_specialist,
    load_domain_profile,
)
from data_agent.review_plus.agent_harness import SPECIALIST_TO_HARNESS_AGENT
from data_agent.review_plus.specialist_orchestration_service import SPECIALIST_CATALOG

_DEFAULT_DOMAIN_ID = "aerospace_review"


@dataclass
class AgentProfile:
    agent_id: str
    display_name: str
    domain: str
    capabilities: list[str] = field(default_factory=list)
    preferred_execution: str = "deterministic"
    requires_evidence: bool = True
    model_tier: str | None = None
    skill_refs: list[str] = field(default_factory=list)
    domain_id: str = _DEFAULT_DOMAIN_ID

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "display_name": self.display_name,
            "domain": self.domain,
            "capabilities": list(self.capabilities),
            "preferred_execution": self.preferred_execution,
            "requires_evidence": self.requires_evidence,
            "model_tier": self.model_tier,
            "skill_refs": list(self.skill_refs),
            "domain_id": self.domain_id,
        }

    def summary(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "display_name": self.display_name,
            "domain": self.domain,
            "preferred_execution": self.preferred_execution,
            "skill_refs": list(self.skill_refs),
            "domain_id": self.domain_id,
        }


def _preferred_execution(specialist_id: str, domain_id: str) -> str:
    harness_id = harness_agent_for_specialist(specialist_id, domain_id)
    if not harness_id:
        harness_id = SPECIALIST_TO_HARNESS_AGENT.get(specialist_id)
    if harness_id:
        return "harness"
    if specialist_id == "document_format_reviewer":
        return "deterministic"
    return "deterministic"


def profile_for_specialist(
    specialist_id: str,
    domain_id: str = _DEFAULT_DOMAIN_ID,
) -> AgentProfile:
    try:
        profile = load_domain_profile(domain_id)
    except KeyError:
        profile = default_domain_profile()
        domain_id = profile.domain_id

    catalog = profile.specialists.get(specialist_id) or SPECIALIST_CATALOG.get(specialist_id) or {}
    skill_ref = profile.skill_refs.get(specialist_id)
    skill_refs = [skill_ref] if skill_ref else []

    return AgentProfile(
        agent_id=specialist_id,
        display_name=str(catalog.get("name") or specialist_id),
        domain=profile.specialist_domains.get(specialist_id, "通用审查"),
        capabilities=[str(item) for item in catalog.get("triggers") or [] if str(item) != "all"],
        preferred_execution=_preferred_execution(specialist_id, domain_id),
        requires_evidence=specialist_id != "document_format_reviewer",
        model_tier="general",
        skill_refs=skill_refs,
        domain_id=domain_id,
    )


def profiles_for_specialists(
    specialist_ids: list[str],
    domain_id: str = _DEFAULT_DOMAIN_ID,
) -> list[AgentProfile]:
    return [profile_for_specialist(specialist_id, domain_id=domain_id) for specialist_id in specialist_ids]


__all__ = [
    "AgentProfile",
    "profile_for_specialist",
    "profiles_for_specialists",
]
