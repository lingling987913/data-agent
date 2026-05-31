"""Domain-specific planner regex rules for satellite review missions."""

from __future__ import annotations

import re

SKIP_RULE_RE = re.compile(
    r"(跳过|不做|无需).{0,8}(规则|review[- ]?plus|合规审查)", re.I
)
SKIP_GNC_RE = re.compile(
    r"(跳过|不做|无需).{0,8}(gnc|总体设计|设计评审)", re.I
)
