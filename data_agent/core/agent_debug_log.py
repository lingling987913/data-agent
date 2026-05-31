"""Agent debug instrumentation — NDJSON logs with human-readable timestamps."""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_LOG = _PROJECT_ROOT / ".cursor" / "debug-aefbf2.log"
_LOG_PATH = Path(os.getenv("AGENT_DEBUG_LOG_PATH", str(_DEFAULT_LOG)))
_SESSION_ID = os.getenv("AGENT_DEBUG_SESSION_ID", "aefbf2")
_CONSOLE = os.getenv("AGENT_DEBUG_CONSOLE", "0").strip().lower() in {"1", "true", "yes", "on"}
_logger = logging.getLogger("data_agent.debug")


def agent_debug_log(
    location: str,
    message: str,
    data: dict[str, Any] | None = None,
    *,
    hypothesis_id: str = "",
    run_id: str = "",
) -> None:
    # #region agent log
    now = time.time()
    entry: dict[str, Any] = {
        "timestamp": int(now * 1000),
        "datetime": datetime.fromtimestamp(now).isoformat(timespec="milliseconds"),
        "location": location,
        "message": message,
        "data": data or {},
    }
    if _SESSION_ID:
        entry["sessionId"] = _SESSION_ID
    if hypothesis_id:
        entry["hypothesisId"] = hypothesis_id
    if run_id:
        entry["runId"] = run_id
    try:
        _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_LOG_PATH, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass
    if _CONSOLE:
        parts = [entry["datetime"], location, message]
        if data:
            parts.append(json.dumps(data, ensure_ascii=False))
        _logger.info(" | ".join(parts))
    # #endregion
