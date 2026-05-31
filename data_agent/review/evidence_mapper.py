from __future__ import annotations

import re
from typing import Any

from data_agent.review.schemas import (
    ReviewPlusCheckItem,
    ReviewPlusFinding,
    ReviewPlusJudgment,
    ReviewPlusMaterialRole,
)

_TOKEN_RE = re.compile(r"[\u4e00-\u9fffA-Za-z0-9]{2,}")


def _tokens(text: str) -> set[str]:
    return {t.lower() for t in _TOKEN_RE.findall(text or "") if len(t) >= 2}


def _item_text(item: ReviewPlusCheckItem) -> str:
    return " ".join(
        part for part in [item.title, item.requirement_text, item.applicable_scope] if part
    )


def _score_overlap(query_tokens: set[str], text: str) -> float:
    if not query_tokens:
        return 0.0
    doc_tokens = _tokens(text)
    if not doc_tokens:
        return 0.0
    overlap = query_tokens & doc_tokens
    if not overlap:
        return 0.0
    return len(overlap) / max(len(query_tokens), 1)


def map_check_items_to_evidence(
    check_items: list[ReviewPlusCheckItem],
    evidence_pools: dict[str, list[dict[str, Any]]],
    *,
    min_score: float = 0.15,
    top_k: int = 3,
) -> list[ReviewPlusFinding]:
    """Deterministic keyword overlap mapping from check items to evidence pool."""
    findings: list[ReviewPlusFinding] = []

    flat_evidence: list[dict[str, Any]] = []
    for file_name, evidences in evidence_pools.items():
        for ev in evidences:
            flat_evidence.append({
                **ev,
                "ref": f"ev:{file_name}:{ev.get('evidence_id', '')}",
                "file_name": file_name,
                "text": " ".join(
                    str(ev.get(field, "") or "")
                    for field in ("summary", "excerpt", "section_id")
                ),
            })

    for item in check_items:
        query = _tokens(_item_text(item))
        scored = []
        for ev in flat_evidence:
            score = _score_overlap(query, ev["text"])
            if score >= min_score:
                scored.append((score, ev))
        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[:top_k]

        if not top:
            findings.append(
                ReviewPlusFinding(
                    check_item_id=item.check_item_id,
                    judgment=ReviewPlusJudgment.INSUFFICIENT_EVIDENCE,
                    severity=item.severity or "minor",
                    title=item.title or item.requirement_text[:80],
                    reasoning="未在送审材料中找到足够证据支撑该检查项。",
                    recommendation="补充对应章节内容或提供更明确的引用关系。",
                    confidence=0.4,
                )
            )
            continue

        best_score, best_ev = top[0]
        quotes = [ev["text"][:300] for _, ev in top if ev.get("text")]
        refs = [ev["ref"] for _, ev in top]

        # 有证据但分数一般 -> 仍标记为证据不足，避免误报"全部通过"
        if best_score < 0.35:
            judgment = ReviewPlusJudgment.INSUFFICIENT_EVIDENCE
            reasoning = "找到部分相关内容，但证据覆盖不足，需人工复核。"
        else:
            judgment = ReviewPlusJudgment.SATISFIED
            reasoning = "在送审材料中找到与检查要求相关的证据段落。"

        findings.append(
            ReviewPlusFinding(
                check_item_id=item.check_item_id,
                judgment=judgment,
                severity=item.severity or "minor",
                title=item.title or item.requirement_text[:80],
                reasoning=reasoning,
                evidence_refs=refs,
                source_quotes=quotes,
                confidence=min(0.95, 0.5 + best_score),
            )
        )

    return findings
