"""Team output_schema example with per-run override."""

from __future__ import annotations

from typing import Any

from data_agent.agno_structured.level_adapter import StructuredLevel, build_agent_kwargs
from data_agent.agno_structured.provider_capability_probe import probe_provider_capabilities
from data_agent.agno_structured.schemas import EntityExtractionOutput, TeamSummaryOutput
from data_agent.agno_structured.validation import validate_structured_output


def create_team_with_output_schema() -> Any:
    """Build Agno Team where members and team leader share structured output config."""
    from agno.agent import Agent
    from agno.team import Team

    cap = probe_provider_capabilities()

    member_kwargs = build_agent_kwargs(
        cap,
        output_schema=EntityExtractionOutput,
        level=StructuredLevel.B,
        instructions=["Extract one entity from the assigned text."],
    )
    researcher = Agent(
        id="aero:agno_structured_member",
        name="Researcher",
        **member_kwargs,
    )

    team_kwargs = build_agent_kwargs(
        cap,
        output_schema=TeamSummaryOutput,
        level=StructuredLevel.B,
        instructions=[
            "Coordinate the researcher and produce a team summary.",
            "Final response must match TeamSummaryOutput.",
        ],
    )
    return Team(
        id="aero:agno_structured_team",
        name="Structured Output Team",
        members=[researcher],
        **team_kwargs,
    )


def run_team_example(user_input: str) -> TeamSummaryOutput:
    team = create_team_with_output_schema()
    # Per-run output_schema override (Agno supports this on agent.run and team.run)
    response = team.run(
        user_input,
        output_schema=TeamSummaryOutput,
    )
    return validate_structured_output(response.content, TeamSummaryOutput)
