"""Strict tool-based structured output fallback (Level D)."""

from __future__ import annotations

from typing import Any

from agno.tools import tool

from data_agent.agno_structured.schemas import StrictToolPayload
from data_agent.agno_structured.validation import validate_structured_output


@tool(strict=True)
def emit_structured_answer(answer: str, sources: list[str]) -> dict[str, Any]:
    """Emit structured answer via strict tool schema (Level D fallback)."""
    payload = StrictToolPayload(answer=answer, sources=sources)
    return payload.model_dump()


def create_strict_tool_agent() -> Any:
    """Agent that returns structured data through a strict tool instead of output_schema."""
    from agno.agent import Agent

    from data_agent.core.models import get_model

    return Agent(
        id="aero:agno_structured_strict_tool",
        name="Strict Tool Agent",
        model=get_model(),
        tools=[emit_structured_answer],
        tool_call_limit=2,
        instructions=[
            "Answer the user question.",
            "You MUST call emit_structured_answer with answer and sources.",
        ],
        markdown=False,
    )


def extract_from_tool_response(response: Any) -> StrictToolPayload:
    """Parse strict tool result from Agno RunOutput."""
    tools = getattr(response, "tools", None) or []
    for execution in tools:
        result = getattr(execution, "result", None)
        if isinstance(result, dict) and "answer" in result:
            return validate_structured_output(result, StrictToolPayload)
    content = getattr(response, "content", None)
    if content is not None:
        return validate_structured_output(content, StrictToolPayload)
    raise ValueError("No strict tool result found in agent response")
