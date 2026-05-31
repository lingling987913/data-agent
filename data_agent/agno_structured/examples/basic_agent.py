"""Basic Agno Agent with structured output adaptation."""

from __future__ import annotations

from typing import Any

from data_agent.agno_structured.level_adapter import StructuredLevel, build_agent_kwargs
from data_agent.agno_structured.provider_capability_probe import probe_provider_capabilities
from data_agent.agno_structured.schemas import EntityExtractionOutput
from data_agent.agno_structured.validation import validate_structured_output


def create_basic_structured_agent(
    *,
    level: StructuredLevel | None = None,
    instructions: list[str] | None = None,
) -> Any:
    """Build an Agno Agent with level-adapted structured output settings."""
    from agno.agent import Agent

    cap = probe_provider_capabilities()
    kwargs = build_agent_kwargs(
        cap,
        output_schema=EntityExtractionOutput,
        level=level,
        instructions=instructions
        or [
            "Extract the primary entity from the user text.",
            "Return JSON matching the output schema.",
        ],
    )
    return Agent(
        id="aero:agno_structured_basic",
        name="Structured Basic Agent",
        **kwargs,
    )


def run_basic_example(user_input: str) -> EntityExtractionOutput:
    """Run basic structured agent and validate output."""
    agent = create_basic_structured_agent()
    response = agent.run(user_input)
    return validate_structured_output(response.content, EntityExtractionOutput)
