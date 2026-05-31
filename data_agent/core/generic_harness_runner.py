"""Generic LLM harness runner for SMART committee specialists (generic domain)."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Protocol

from data_agent.core.config import is_smart_generic_llm_enabled
from data_agent.core.llm_profiles import LLMProfile, get_llm_profile

logger = logging.getLogger(__name__)

EXECUTION_MODE_GENERIC_LLM = "generic_llm_harness"

_SYSTEM_PROMPT = """你是文档审查专家。请基于提供的审查目标、专家职责、材料与检查项完成单专家审查。

输出要求：
1. 优先返回 JSON 对象（不要用 markdown 代码块包裹），结构如下：
{
  "summary": "一段简短审查结论",
  "findings": [
    {
      "title": "发现标题",
      "description": "详细说明",
      "severity": "critical|major|minor|info",
      "evidence_refs": ["evidence_id 或引用片段"],
      "source_quotes": ["原文摘录"]
    }
  ]
}
2. findings 应具体、可行动；severity 默认为 info。
3. 每条 finding 尽量引用 evidence_pool / source_evidence_refs 中的 evidence_id。
4. 若无法引用任何证据，仍应给出 finding，但 evidence_refs 可为空。"""


class GenericHarnessUnavailable(Exception):
    """Raised when generic LLM harness cannot run (controlled fallback)."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class GenericHarnessError(Exception):
    """Raised when generic LLM harness fails after attempt (controlled fallback)."""

    def __init__(self, reason: str, *, cause: Exception | None = None) -> None:
        self.reason = reason
        self.cause = cause
        super().__init__(reason)


class GenericLLMClient(Protocol):
    def complete(self, *, system: str, user: str) -> str: ...


class ProfileBackedGenericLLMClient:
    """Sync OpenAI-compatible client backed by centralized LLM profiles."""

    def __init__(self, profile: LLMProfile) -> None:
        self._profile = profile

    def complete(self, *, system: str, user: str) -> str:
        import openai

        client = openai.OpenAI(
            api_key=self._profile.api_key,
            base_url=self._profile.base_url,
            timeout=self._profile.timeout,
        )
        create_kwargs: dict[str, Any] = {
            "model": self._profile.model,
            "temperature": 0.0,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        if self._profile.max_tokens is not None:
            create_kwargs["max_tokens"] = self._profile.max_tokens
        if self._profile.extra_body:
            create_kwargs["extra_body"] = self._profile.extra_body

        resp = client.chat.completions.create(**create_kwargs)
        if not resp.choices:
            return ""
        return (resp.choices[0].message.content or "").strip()


def generic_llm_availability() -> tuple[bool, str]:
    """Return (available, reason). reason is empty when available."""
    if not is_smart_generic_llm_enabled():
        return False, "disabled"
    profile = get_llm_profile("general")
    if not profile.is_complete():
        return False, "llm_not_configured"
    return True, ""


def get_generic_llm_client() -> GenericLLMClient | None:
    available, _ = generic_llm_availability()
    if not available:
        return None
    return ProfileBackedGenericLLMClient(get_llm_profile("general"))


def _materials_text(context: dict[str, Any]) -> str:
    corpus = str(context.get("corpus_text") or "").strip()
    if corpus:
        return corpus[:12000]
    chunks: list[str] = []
    for item in context.get("materials") or []:
        if not isinstance(item, dict):
            continue
        content = str(item.get("content") or "").strip()
        if content:
            name = str(item.get("name") or item.get("role") or "material")
            chunks.append(f"[{name}]\n{content[:4000]}")
    return "\n\n".join(chunks)[:12000]


def _check_items_text(context: dict[str, Any]) -> str:
    items = context.get("check_items") or context.get("synthetic_check_items") or []
    lines: list[str] = []
    for item in items[:12]:
        if not isinstance(item, dict):
            continue
        cid = str(item.get("check_item_id") or item.get("id") or "")
        title = str(item.get("title") or "")
        req = str(item.get("requirement_text") or item.get("description") or title)
        quote = str(item.get("source_quote") or "")
        line = f"- [{cid or title}] {req}"
        if quote:
            line += f" | 依据: {quote[:200]}"
        lines.append(line)
    return "\n".join(lines) if lines else "（无合成检查项）"


def _evidence_pool_text(context: dict[str, Any]) -> str:
    lines: list[str] = []
    pool = context.get("evidence_pool")
    if isinstance(pool, dict):
        for ev in pool.get("evidences") or []:
            if not isinstance(ev, dict):
                continue
            eid = str(ev.get("evidence_id") or "")
            excerpt = str(ev.get("excerpt") or ev.get("quote") or "")[:300]
            if eid or excerpt:
                lines.append(f"- {eid}: {excerpt}")
    for ref in context.get("source_evidence_refs") or []:
        if not isinstance(ref, dict):
            continue
        eid = str(ref.get("evidence_id") or "")
        excerpt = str(ref.get("excerpt") or ref.get("quote") or ref.get("text") or "")[:300]
        if eid or excerpt:
            lines.append(f"- {eid}: {excerpt}")
    return "\n".join(lines[:20]) if lines else "（无证据池）"


def _build_user_prompt(
    *,
    specialist_id: str,
    profile: dict[str, Any],
    context: dict[str, Any],
) -> str:
    objective = str(context.get("objective") or "").strip()
    display_name = str(profile.get("display_name") or specialist_id)
    capabilities = profile.get("capabilities") or []
    cap_text = "、".join(str(c) for c in capabilities[:8]) if capabilities else "通用文档审查"
    synthetic_book = str(context.get("synthetic_task_book") or "").strip()

    sections = [
        f"## 审查目标\n{objective or '（未指定，请审查文档核心结论与一致性）'}",
        f"## 专家\nID: {specialist_id}\n名称: {display_name}\n职责: {cap_text}",
    ]
    if synthetic_book:
        sections.append(f"## 合成任务书\n{synthetic_book[:4000]}")
    sections.extend(
        [
            f"## 合成/结构化检查项\n{_check_items_text(context)}",
            f"## 证据池 / 引用\n{_evidence_pool_text(context)}",
            f"## 审查材料\n{_materials_text(context) or '（无正文）'}",
        ]
    )
    return "\n\n".join(sections)


def _strip_json_fence(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.IGNORECASE)
        stripped = re.sub(r"\s*```$", "", stripped)
    return stripped.strip()


def _normalize_severity(value: Any) -> str:
    raw = str(value or "info").strip().lower()
    if raw in {"critical", "major", "minor", "info"}:
        return raw
    return "info"


def _normalize_evidence_refs(raw_refs: Any, source_quotes: Any) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _append(ref_id: str, *, quote: str = "", source: str = "llm") -> None:
        ref_id = ref_id.strip()
        if not ref_id or ref_id in seen:
            return
        seen.add(ref_id)
        entry: dict[str, Any] = {"evidence_id": ref_id, "source": source}
        if quote:
            entry["quote"] = quote[:400]
        refs.append(entry)

    if isinstance(raw_refs, list):
        for item in raw_refs:
            if isinstance(item, dict):
                _append(
                    str(item.get("evidence_id") or item.get("id") or ""),
                    quote=str(item.get("quote") or item.get("excerpt") or ""),
                )
            elif item is not None:
                _append(str(item))

    if isinstance(source_quotes, list):
        for quote in source_quotes:
            text = str(quote or "").strip()
            if text:
                _append(text[:80], quote=text, source="source_quote")

    return refs


def _parse_llm_payload(raw: str, *, specialist_id: str) -> tuple[list[dict[str, Any]], str, list[dict[str, Any]]]:
    text = _strip_json_fence(raw)
    summary_message = ""
    findings: list[dict[str, Any]] = []
    evidence_refs: list[dict[str, Any]] = []

    parsed: dict[str, Any] | None = None
    if text.startswith("{"):
        try:
            loaded = json.loads(text)
            if isinstance(loaded, dict):
                parsed = loaded
        except json.JSONDecodeError:
            parsed = None

    if parsed is not None:
        summary_message = str(parsed.get("summary") or parsed.get("message") or "").strip()
        for idx, item in enumerate(parsed.get("findings") or []):
            if not isinstance(item, dict):
                continue
            refs = _normalize_evidence_refs(
                item.get("evidence_refs") or item.get("source_evidence_ids"),
                item.get("source_quotes"),
            )
            finding = {
                "review_item_id": f"{specialist_id}-generic-llm-{idx + 1}",
                "item_type": "generic_llm_review",
                "severity": _normalize_severity(item.get("severity")),
                "title": str(item.get("title") or f"发现 {idx + 1}"),
                "description": str(item.get("description") or item.get("detail") or ""),
                "agent_id": specialist_id,
                "evidence_refs": refs,
            }
            if refs:
                finding["source_evidence_ids"] = [r["evidence_id"] for r in refs]
            findings.append(finding)
            evidence_refs.extend(refs)
    else:
        summary_message = text[:800].strip()
        if summary_message:
            findings.append(
                {
                    "review_item_id": f"{specialist_id}-generic-llm-1",
                    "item_type": "generic_llm_review",
                    "severity": "info",
                    "title": "LLM 审查结论",
                    "description": summary_message,
                    "agent_id": specialist_id,
                    "evidence_refs": [],
                }
            )

    deduped_refs: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for ref in evidence_refs:
        ref_id = str(ref.get("evidence_id") or "")
        if ref_id and ref_id not in seen_ids:
            seen_ids.add(ref_id)
            deduped_refs.append(ref)

    return findings, summary_message, deduped_refs


def run_generic_specialist_review(
    specialist_id: str,
    profile: dict[str, Any],
    context: dict[str, Any],
    *,
    llm_client: GenericLLMClient | None = None,
) -> dict[str, Any]:
    """Run a single generic-domain specialist review via LLM.

    Raises GenericHarnessUnavailable when disabled or client missing.
    Raises GenericHarnessError on LLM/parsing failures.
    """
    available, reason = generic_llm_availability()
    if not available:
        raise GenericHarnessUnavailable(reason)

    client = llm_client or get_generic_llm_client()
    if client is None:
        raise GenericHarnessUnavailable("llm_not_configured")

    objective = str(context.get("objective") or "").strip()
    user_prompt = _build_user_prompt(
        specialist_id=specialist_id,
        profile=profile,
        context=context,
    )

    try:
        raw = client.complete(system=_SYSTEM_PROMPT, user=user_prompt)
    except Exception as exc:
        logger.warning(
            "[generic_harness] LLM call failed specialist=%s: %s",
            specialist_id,
            exc,
        )
        raise GenericHarnessError(f"llm_call_failed:{exc.__class__.__name__}", cause=exc) from exc

    if not str(raw or "").strip():
        raise GenericHarnessError("empty_llm_response")

    findings, summary_message, evidence_refs = _parse_llm_payload(raw, specialist_id=specialist_id)
    limited = not bool(evidence_refs)
    display_name = str(profile.get("display_name") or specialist_id)
    focus = (
        f"围绕审查目标「{objective}」完成 {display_name} LLM Harness 专家审查。"
        if objective
        else f"已完成 {display_name} LLM Harness 专家审查。"
    )
    summary: dict[str, Any] = {
        "message": summary_message or focus,
        "review_focus": focus,
        "objective": objective,
        "finding_count": len(findings),
        "execution_mode": EXECUTION_MODE_GENERIC_LLM,
        "harness_strategy": "generic_harness",
        "limited": limited,
        "specialist_id": specialist_id,
        "generic_llm": True,
    }

    return {
        "agent_id": specialist_id,
        "agent_name": display_name,
        "role": str(profile.get("role") or ""),
        "status": "completed",
        "findings": findings,
        "summary": summary,
        "evidence_refs": evidence_refs,
        "citations": evidence_refs,
        "harness_strategy": "generic_harness",
        "execution_mode": EXECUTION_MODE_GENERIC_LLM,
        "objective": objective,
        "limited": limited,
    }


__all__ = [
    "EXECUTION_MODE_GENERIC_LLM",
    "GenericHarnessError",
    "GenericHarnessUnavailable",
    "GenericLLMClient",
    "ProfileBackedGenericLLMClient",
    "generic_llm_availability",
    "get_generic_llm_client",
    "run_generic_specialist_review",
]
