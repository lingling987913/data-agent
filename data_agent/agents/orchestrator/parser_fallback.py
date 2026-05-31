"""Parser fallback chain with trace logging."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Awaitable

from data_agent.agents.orchestrator.schemas import ParserFallbackLog

logger = logging.getLogger(__name__)

ParserFn = Callable[[], Awaitable[dict[str, Any]]]

PARSER_CHAIN = (
    ("mineru_online", "MinerU Online API"),
    ("mineru_local", "Local MinerU Parser"),
    ("pdf2text", "本地 pdf2text/docx2txt"),
)


@dataclass
class ParserFallbackConfig:
    max_retries: int = 2
    timeout_sec: float = 3.0


@dataclass
class ParserFallbackRunner:
    """Execute parsers in degradation order; record fallback logs."""

    config: ParserFallbackConfig = field(default_factory=ParserFallbackConfig)
    logs: list[ParserFallbackLog] = field(default_factory=list)

    async def run(
        self,
        parsers: dict[str, ParserFn],
        *,
        file_name: str = "",
    ) -> dict[str, Any]:
        """
        Try parsers in chain order. Each parser is invoked with timeout.

        ``parsers`` maps chain key -> async callable returning result dict.
        Missing keys are skipped.
        """
        last_error = "no parser available"
        for idx, (key, label) in enumerate(PARSER_CHAIN):
            fn = parsers.get(key)
            if fn is None:
                continue
            for attempt in range(self.config.max_retries + 1):
                try:
                    result = await asyncio.wait_for(
                        fn(),
                        timeout=self.config.timeout_sec,
                    )
                    if idx > 0:
                        self._log_fallback(
                            source=PARSER_CHAIN[idx - 1][0],
                            target=key,
                            reason=last_error,
                            recovered=True,
                            retry_count=attempt,
                        )
                    return {**result, "parser_used": key, "parser_label": label}
                except Exception as exc:
                    last_error = str(exc)
                    logger.warning(
                        "[ParserFallback] %s attempt %s failed: %s",
                        key,
                        attempt + 1,
                        exc,
                    )
                    if idx < len(PARSER_CHAIN) - 1:
                        next_key = PARSER_CHAIN[idx + 1][0]
                        self._log_fallback(
                            source=key,
                            target=next_key,
                            reason=last_error,
                            recovered=False,
                            retry_count=attempt,
                        )
        raise RuntimeError(f"All parsers failed for {file_name or 'document'}: {last_error}")

    def _log_fallback(
        self,
        *,
        source: str,
        target: str,
        reason: str,
        recovered: bool,
        retry_count: int,
    ) -> None:
        self.logs.append(
            ParserFallbackLog(
                timestamp=datetime.now(timezone.utc).isoformat(),
                source=source,
                target=target,
                reason=reason,
                recovered=recovered,
                retry_count=retry_count,
            )
        )


async def mock_parser_success(parser_key: str) -> dict[str, Any]:
    """Test helper: simulated successful parse."""
    await asyncio.sleep(0)
    return {"status": "ok", "blocks": 0, "mock": True, "parser": parser_key}


async def mock_parser_fail(_: str = "") -> dict[str, Any]:
    """Test helper: always raises."""
    await asyncio.sleep(0)
    raise TimeoutError("simulated parser failure")
