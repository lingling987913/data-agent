from __future__ import annotations

import logging
import os
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class ComplianceAgentOutput(BaseModel):
    enhanced_reasoning: str = ""
    recommendation: str = ""


def _agents_enabled() -> bool:
    return bool(os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")) and os.getenv(
        "COMPLIANCE_AGENTS_ENABLED", "1"
    ).strip().lower() not in {"0", "false", "no", "off"}


def enhance_finding_with_agent(
    *,
    check_title: str,
    requirement: str,
    evidence_quotes: list[str],
) -> ComplianceAgentOutput | None:
    """Optional LLM enhancement for a single finding. Returns None if disabled."""
    if not _agents_enabled():
        return None
    try:
        from agno.agent import Agent

        from data_agent.agno_structured import (
            build_agent_kwargs,
            probe_provider_capabilities,
            run_agent_with_validation,
        )

        cap = probe_provider_capabilities(role="general")
        agent = Agent(
            **build_agent_kwargs(
                cap,
                id="data-agent:compliance",
                name="ComplianceReviewAgent",
                output_schema=ComplianceAgentOutput,
                instructions=[
                    "你是航天产品保证审查专家。",
                    "基于给定检查项与证据摘录，输出简要审查理由和改进建议。",
                    "禁止编造证据中不存在的数值或结论。",
                ],
            )
        )
        prompt = (
            f"检查项: {check_title}\n"
            f"要求: {requirement}\n"
            f"证据摘录:\n" + "\n---\n".join(evidence_quotes[:3])
        )
        return run_agent_with_validation(agent, prompt, ComplianceAgentOutput)
    except Exception as exc:
        logger.warning("ComplianceAgent enhancement skipped: %s", exc)
    return None
