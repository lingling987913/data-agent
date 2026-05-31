"""Thread-safe accumulation of LLM call costs for evaluation."""

from __future__ import annotations

import threading
import uuid
from typing import Protocol

from data_agent.agents.inspector.schemas import CostSummary, LLMCallDetail

# Rough USD per token for MVP cost estimates (not billing-grade).
_COST_PER_TOKEN_USD = 2.0e-6


class CostTrackerProtocol(Protocol):
    """Structural type for structuring modules (avoids circular imports)."""

    def record_call(
        self,
        component: str,
        model_id: str,
        latency_ms: int,
        *,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        total_tokens: int = 0,
        status: str = "ok",
    ) -> None: ...


class CostTracker:
    """Thread-safe tracker for LLM call details and aggregated cost."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._calls: list[LLMCallDetail] = []

    def record_call(
        self,
        component: str,
        model_id: str,
        latency_ms: int,
        *,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        total_tokens: int = 0,
        status: str = "ok",
    ) -> LLMCallDetail:
        if total_tokens <= 0 and (prompt_tokens or completion_tokens):
            total_tokens = prompt_tokens + completion_tokens
        detail = LLMCallDetail(
            call_id=str(uuid.uuid4()),
            component=component,
            model_id=model_id,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            latency_ms=latency_ms,
            status=status,
        )
        with self._lock:
            self._calls.append(detail)
        return detail

    def summary(self) -> CostSummary:
        with self._lock:
            calls = list(self._calls)
        total_tokens = sum(c.total_tokens for c in calls)
        total_latency = sum(c.latency_ms for c in calls)
        return CostSummary(
            llm_call_count=len(calls),
            api_call_count=len(calls),
            total_tokens=total_tokens,
            total_latency_ms=total_latency,
            estimated_cost_usd=total_tokens * _COST_PER_TOKEN_USD,
            calls=calls,
        )
