#!/usr/bin/env python3
"""Minimal smoke test for Agno structured output adaptation layer."""

from __future__ import annotations

import json
import os
import sys


def main() -> int:
    from data_agent.agno_structured.level_adapter import StructuredLevel, describe_level, select_level_from_capabilities
    from data_agent.agno_structured.provider_capability_probe import (
        build_capability_matrix,
        probe_provider_capabilities,
    )
    from data_agent.agno_structured.schemas import EntityExtractionOutput
    from data_agent.agno_structured.validation import validate_structured_output

    print("=== Agno Structured Output Smoke Test ===")

    cap = probe_provider_capabilities()
    level = select_level_from_capabilities(cap)
    print(f"Provider: {cap.provider.value} model={cap.model}")
    print(f"Recommended level: {level.value} — {describe_level(level)}")
    print(f"Probe mode: {cap.probe_mode} verified={cap.verified} mock_only={cap.mock_only}")
    if cap.probe_errors:
        print("Probe errors:", cap.probe_errors)

    matrix = build_capability_matrix([cap])
    print("Capability matrix:")
    print(json.dumps(matrix, ensure_ascii=False, indent=2))

    # Offline validation path (no API)
    sample = {"entity": "长征五号", "category": "运载火箭", "confidence": 0.92}
    validated = validate_structured_output(sample, EntityExtractionOutput)
    print(f"Validation OK: {validated.model_dump()}")

    run_live = os.getenv("AGNO_STRUCTURED_SMOKE_LIVE", "").lower() in {"1", "true", "yes"}
    if run_live:
        from data_agent.agno_structured.examples.basic_agent import run_basic_example

        print("\nRunning live basic agent example...")
        result = run_basic_example("分析实体：北斗三号导航卫星")
        print("Live result:", result.model_dump())
    else:
        print("\nSkipping live agent run (set AGNO_STRUCTURED_SMOKE_LIVE=1 to enable).")

    print("\nSmoke test passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
