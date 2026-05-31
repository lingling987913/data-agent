"""Wizard phase handlers for Super Agent five-step flow."""

from __future__ import annotations

from typing import TYPE_CHECKING

from data_agent.super_agent.phases.base import (
    PHASE_WIZARD_STEP,
    WIZARD_PHASE_IDS,
    PhaseContext,
    PhaseHandlerBase,
    PhaseRegistry,
    RunHost,
    WizardPhaseHandler,
    advance_wizard_phase,
)
from data_agent.super_agent.phases.classify_and_route import ClassifyAndRoutePhaseHandler
from data_agent.super_agent.phases.document_parse import DocumentParsePhaseHandler
from data_agent.super_agent.phases.document_review import DocumentReviewPhaseHandler
from data_agent.super_agent.phases.review_results import ReviewResultsPhaseHandler
from data_agent.super_agent.phases.upload import UploadPhaseHandler

if TYPE_CHECKING:
    pass


def build_phase_registry(host: RunHost) -> PhaseRegistry:
    return PhaseRegistry(
        upload=UploadPhaseHandler(host),
        classify_and_route=ClassifyAndRoutePhaseHandler(host),
        document_parse=DocumentParsePhaseHandler(host),
        document_review=DocumentReviewPhaseHandler(host),
        review_results=ReviewResultsPhaseHandler(host),
    )


__all__ = [
    "PHASE_WIZARD_STEP",
    "WIZARD_PHASE_IDS",
    "ClassifyAndRoutePhaseHandler",
    "DocumentParsePhaseHandler",
    "DocumentReviewPhaseHandler",
    "PhaseContext",
    "PhaseHandlerBase",
    "PhaseRegistry",
    "ReviewResultsPhaseHandler",
    "RunHost",
    "UploadPhaseHandler",
    "WizardPhaseHandler",
    "advance_wizard_phase",
    "build_phase_registry",
]
