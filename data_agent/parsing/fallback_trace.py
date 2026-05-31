from __future__ import annotations

from datetime import datetime, timezone


def record_parser_fallback(
    logs: list[dict],
    *,
    source_parser: str,
    fallback_parser: str,
    reason: str,
    recovered: bool,
    elapsed_ms: int = 0,
) -> None:
    logs.append(
        {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source_parser": source_parser,
            "fallback_parser": fallback_parser,
            "reason": reason,
            "recovered": recovered,
            "elapsed_ms": elapsed_ms,
        }
    )
