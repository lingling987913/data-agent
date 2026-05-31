from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
UPLOAD_DIR = PROJECT_ROOT / "storage" / "uploads"

_env_file = PROJECT_ROOT / ".env"
if _env_file.exists():
    load_dotenv(_env_file, override=False)


def _resolve_runs_dir() -> Path:
    """Root for all run-scoped artifacts (traces, checkpoints, Super Agent runs, etc.).

    Override at deploy time via ``DATA_AGENT_RUNS_DIR``; default is ``{project}/storage/runs``.
    """
    raw = os.getenv("DATA_AGENT_RUNS_DIR", "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return (PROJECT_ROOT / "storage" / "runs").resolve()


# Default layout under RUNS_DIR:
#   traces/ checkpoints/ tasks/ review_data_agent_runs/ review_plus_tasks/
#   review_plus_reports/ gnc_tasks/ task_boards/
RUNS_DIR = _resolve_runs_dir()
TRACES_DIR = RUNS_DIR / "traces"
CHECKPOINTS_DIR = RUNS_DIR / "checkpoints"
REVIEW_PLUS_REPORTS_DIR = RUNS_DIR / "review_plus_reports"
# Pre-layout-fix Review-Plus reports lived directly under storage/ (not under runs/).
LEGACY_REVIEW_PLUS_REPORTS_DIR = PROJECT_ROOT / "storage" / "review_plus_reports"
SUPER_AGENT_RUNS_DIR = RUNS_DIR / "review_data_agent_runs"
GNC_RUNS_DIR = RUNS_DIR / "gnc_tasks"

SUPER_AGENT_UPLOAD_DIR = Path(os.getenv("SUPER_AGENT_UPLOAD_DIR", str(UPLOAD_DIR / "super_agent")))


def ensure_dirs() -> None:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    SUPER_AGENT_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    TRACES_DIR.mkdir(parents=True, exist_ok=True)
    CHECKPOINTS_DIR.mkdir(parents=True, exist_ok=True)
    REVIEW_PLUS_REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    (RUNS_DIR / "tasks").mkdir(parents=True, exist_ok=True)
    (RUNS_DIR / "review_plus_tasks").mkdir(parents=True, exist_ok=True)
    SUPER_AGENT_RUNS_DIR.mkdir(parents=True, exist_ok=True)
    GNC_RUNS_DIR.mkdir(parents=True, exist_ok=True)
    (UPLOAD_DIR / "gnc").mkdir(parents=True, exist_ok=True)
    if is_task_board_file_store_enabled():
        (RUNS_DIR / "task_boards").mkdir(parents=True, exist_ok=True)


def get_api_token() -> str:
    return os.getenv("API_TOKEN", "dev-token-change-me")


def get_env(key: str, default: str = "") -> str:
    return os.getenv(key, default)


def _env_bool(key: str, default: bool = True) -> bool:
    raw = os.getenv(key)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_int(key: str, default: int) -> int:
    raw = os.getenv(key)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw.strip())
    except ValueError:
        return default


def is_structuring_enabled() -> bool:
    return _env_bool("STRUCTURING_ENABLED", default=True)


def get_structuring_processing_mode() -> str:
    return get_env("STRUCTURING_DEFAULT_MODE", "OPTIMAL") or "OPTIMAL"


def get_structuring_context_blocks() -> int:
    return max(0, _env_int("STRUCTURING_CONTEXT_BLOCKS", 2))


def get_structuring_max_repair_blocks() -> int:
    return max(0, _env_int("STRUCTURING_MAX_REPAIR_BLOCKS", 50))


def get_structuring_llm_timeout() -> int:
    return max(10, _env_int("STRUCTURING_LLM_TIMEOUT", 120))


def _lightweight_or_openai_model() -> str:
    """Parsing-tier model: LIGHT_LLM_* → LLM_* (via parsing role chain)."""
    from data_agent.core.llm_profiles import get_llm_profile

    return (
        get_env("STRUCTURING_REPAIR_MODEL")
        or get_llm_profile("parsing").model
        or "gpt-4o-mini"
    )


def get_structuring_repair_model() -> str:
    return get_env("STRUCTURING_REPAIR_MODEL") or _lightweight_or_openai_model()


def get_structuring_anaphora_model() -> str:
    return get_env("STRUCTURING_ANAPHORA_MODEL") or _lightweight_or_openai_model()


def parsing_enable_image_desc() -> bool:
    """When true, embedded figures use VLM even under OPTIMAL mode."""
    return _env_bool("PARSING_ENABLE_IMAGE_DESC", default=False)


def is_smart_generic_llm_enabled() -> bool:
    """When true, generic-domain harness specialists may call the configured LLM client."""
    return _env_bool("SMART_GENERIC_LLM_ENABLED", default=False)


def is_adaptive_router_enabled() -> bool:
    """When true, classify_and_route may use LLM-auxiliary adaptive routing (Hermes P9/P10)."""
    return _env_bool("ADAPTIVE_ROUTER_ENABLED", default=False)


def is_task_board_file_store_enabled() -> bool:
    """When true, persist SMART TaskBoard snapshots under storage/runs/task_boards/."""
    return _env_bool("TASK_BOARD_FILE_STORE_ENABLED", default=False)


def parsing_calibration_enabled() -> bool:
    """Enable parse rationality calibration in non-preview parsing modes."""
    return _env_bool("PARSING_CALIBRATION_ENABLED", default=True)


def get_parsing_calibration_max_blocks() -> int:
    return max(0, _env_int("PARSING_CALIBRATION_MAX_BLOCKS", 50))


def get_parsing_calibration_max_concurrency() -> int:
    return max(1, _env_int("PARSING_CALIBRATION_MAX_CONCURRENCY", 12))


def get_parsing_image_desc_max_concurrency() -> int:
    return max(1, _env_int("PARSING_IMAGE_DESC_MAX_CONCURRENCY", 4))


def get_parsing_calibration_llm_timeout() -> int:
    """Per-request timeout (seconds) for VLM parse rationality calibration."""
    explicit = os.getenv("PARSING_CALIBRATION_LLM_TIMEOUT")
    if explicit is not None and str(explicit).strip():
        try:
            return max(30, int(explicit))
        except ValueError:
            pass
    return max(30, _env_int("STRUCTURING_LLM_TIMEOUT", 300))


def get_parsing_calibration_profile() -> str:
    profile = (get_env("PARSING_CALIBRATION_PROFILE", "vision") or "vision").strip()
    allowed = {
        "general",
        "parsing",
        "vision",
        "formula",
        "lightweight",
        "light_llm",
        "light_vision",
    }
    return profile if profile in allowed else "vision"


def get_parsing_calibration_model() -> str:
    explicit = get_env("PARSING_CALIBRATION_MODEL")
    if explicit:
        return explicit
    from data_agent.core.llm_profiles import get_llm_profile

    return get_llm_profile(get_parsing_calibration_profile()).model or _lightweight_or_openai_model()  # type: ignore[arg-type]


def get_parsing_serial_consensus_min_majority() -> int:
    """Minimum count for the dominant product-serial prefix in a series group."""
    return max(2, _env_int("PARSING_SERIAL_CONSENSUS_MIN_MAJORITY", 2))


def get_parsing_serial_consensus_ratio() -> float:
    """Minimum share (0–1) for the dominant prefix within a series group."""
    raw = os.getenv("PARSING_SERIAL_CONSENSUS_RATIO")
    if raw is not None and str(raw).strip():
        try:
            return max(0.5, min(1.0, float(raw)))
        except ValueError:
            pass
    return 0.75
