"""Dedicated file logging for Agno agent / team / workflow runs."""

from __future__ import annotations

import logging
import os
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_LOG = _PROJECT_ROOT / ".dev" / "logs" / "agno.log"

_CONFIGURED = False
_LOG_PATH: Path | None = None


def _truthy(value: str | None, *, default: bool = True) -> bool:
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


def _build_file_logger(name: str, handler: logging.Handler) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.handlers.clear()
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    logger.addHandler(handler)
    return logger


def setup_agno_file_logging() -> Path | None:
    """Route Agno library logs to ``.dev/logs/agno.log`` (override via AGNO_LOG_PATH)."""
    global _CONFIGURED, _LOG_PATH

    if not _truthy(os.getenv("AGNO_LOG_ENABLED"), default=True):
        return None
    if _CONFIGURED:
        return _LOG_PATH

    log_path = Path(os.getenv("AGNO_LOG_PATH", str(_DEFAULT_LOG)))
    log_path.parent.mkdir(parents=True, exist_ok=True)

    level_name = os.getenv("AGNO_LOG_LEVEL", "DEBUG").upper()
    level = getattr(logging, level_name, logging.DEBUG)
    debug_level_raw = os.getenv("AGNO_DEBUG_LEVEL", "2").strip()
    try:
        debug_level = max(1, min(2, int(debug_level_raw)))
    except ValueError:
        debug_level = 2

    # Import Agno logging first so its module-level Rich console handlers are
    # registered once; then replace them with our file handler only.
    from agno.utils.log import configure_agno_logging, set_log_level_to_debug

    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setLevel(level)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s %(levelname)-8s [%(name)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )

    agent_logger = _build_file_logger("agno", handler)
    team_logger = _build_file_logger("agno-team", handler)
    workflow_logger = _build_file_logger("agno-workflow", handler)

    configure_agno_logging(
        custom_default_logger=agent_logger,
        custom_agent_logger=agent_logger,
        custom_team_logger=team_logger,
        custom_workflow_logger=workflow_logger,
        enable_log_tracebacks=_truthy(os.getenv("AGNO_LOG_TRACEBACKS"), default=False),
    )

    if level <= logging.DEBUG:
        set_log_level_to_debug(level=debug_level)  # type: ignore[arg-type]

    # Safety net: Agno may re-attach Rich console handlers during import/configure.
    for named_logger in (agent_logger, team_logger, workflow_logger):
        named_logger.handlers = [h for h in named_logger.handlers if isinstance(h, logging.FileHandler)]
        named_logger.propagate = False

    _CONFIGURED = True
    _LOG_PATH = log_path

    logging.getLogger(__name__).info("Agno file logging enabled: %s (level=%s)", log_path, level_name)
    return log_path


__all__ = ["setup_agno_file_logging"]
