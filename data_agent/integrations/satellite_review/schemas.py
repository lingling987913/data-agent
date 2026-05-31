"""Satellite review domain task types and agent roles."""

from __future__ import annotations

from enum import Enum


class SatelliteTaskType(str, Enum):
    SLOT_GATEKEEPING = "slot_gatekeeping"
    RULE_REVIEW = "rule_review"
    GNC_REVIEW = "gnc_review"


class SatelliteAgentRole(str, Enum):
    GATEKEEPING = "gatekeeping_agent"
    REVIEW_PLUS = "review_plus_agent"
    GNC_REVIEW = "gnc_review_agent"
