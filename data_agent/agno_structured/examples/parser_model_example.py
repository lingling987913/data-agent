"""parser_model structured output example (Level C)."""

from __future__ import annotations

from typing import Any

from data_agent.agno_structured.level_adapter import StructuredLevel, build_agent_kwargs
from data_agent.agno_structured.provider_capability_probe import probe_provider_capabilities
from data_agent.agno_structured.schemas import EntityExtractionOutput
from data_agent.agno_structured.validation import validate_structured_output


def create_parser_model_agent() -> Any:
    """Main model reasons; parser_model formats structured output."""
    from agno.agent import Agent

    cap = probe_provider_capabilities()
    kwargs = build_agent_kwargs(
        cap,
        output_schema=EntityExtractionOutput,
        level=StructuredLevel.C,
        instructions=[
            "Analyze the user text and identify the primary entity.",
            "Provide reasoning in natural language; structured JSON will be extracted by parser_model.",
        ],
        parser_model_prompt=(
            "Read the assistant response and return ONLY JSON matching EntityExtractionOutput."
        ),
    )
    return Agent(
        id="aero:agno_structured_parser",
        name="Parser Model Agent",
        **kwargs,
    )


def run_parser_model_example(user_input: str) -> EntityExtractionOutput:
    agent = create_parser_model_agent()
    response = agent.run(user_input)
    return validate_structured_output(response.content, EntityExtractionOutput)
