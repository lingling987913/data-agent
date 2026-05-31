"""Business issue buckets for unified review conclusion workbench."""

from __future__ import annotations

import re
from typing import Any, Literal

ReviewMode = Literal["gnc", "review_plus", "super_agent", "generic"]

BUSINESS_BUCKET_KEYS = (
    "severe_error",
    "content_nonconforming",
    "template_structure_nonconforming",
    "cross_document_inconsistency",
    "insufficient_evidence",
    "manual_review",
    "verified",
)

BUSINESS_BUCKET_LABELS: dict[str, str] = {
    "severe_error": "严重错误",
    "content_nonconforming": "内容不合格",
    "template_structure_nonconforming": "模板/结构不合格",
    "cross_document_inconsistency": "文文不一致",
    "insufficient_evidence": "证据不足/无法印证",
    "manual_review": "待人工确认",
    "verified": "已通过/已印证",
}

DEFAULT_INSUFFICIENT_REASON = "系统已知应验证该审查点，但当前上传材料不足以支持通过/不通过判定。"

MATERIAL_INSUFFICIENT_VERDICT = "material_insufficient"
MATERIAL_INSUFFICIENT_HEADLINE = "材料不足，无法完成完整 GNC 审查，请先补齐材料后复审"

_SUSPEND_REVIEW_MARKERS = ("中止审查", "suspend", "aborted", "halted", "stopped")
_BLOCKED_EVIDENCE_MARKERS = (
    "未接收",
    "无主证据",
    "无配套",
    "未提供待审",
    "证据列表为空",
    "不具备开展实质性审查",
    "lack of",
    "missing critical",
    "primary design document",
    "no primary",
)
_REJECTED_VERDICTS = {"conditional_rejection", "conditionally_rejected", "rejected", "not_approved", "fail"}

VERDICT_LABELS_ZH: dict[str, str] = {
    "pass": "通过",
    "passed": "通过",
    "approved": "通过",
    "approve": "通过",
    "conditional_pass": "有条件通过",
    "conditionally_approved": "有条件通过",
    "conditional_rejection": "材料不足，暂无法完成完整审查",
    "conditionally_rejected": "材料不足，暂无法完成完整审查",
    "blocked": "材料不足，暂无法完成完整审查",
    "insufficient_materials": "材料不足，暂无法完成完整审查",
    "material_insufficient": "材料不足，暂无法完成完整审查",
    "reject": "不通过",
    "rejected": "不通过",
    "failed": "不通过",
    "fail": "不通过",
    "not_approved": "不通过",
    "not_passed": "不通过",
    "conditional": "有条件通过",
    "needs_human_review": "待人工确认",
    "needs_review": "待人工确认",
    "pending": "待确认",
}

JUDGMENT_LABELS_ZH: dict[str, str] = {
    "satisfied": "已满足",
    "passed": "通过",
    "pass": "通过",
    "compliant": "符合",
    "not_satisfied": "未满足",
    "insufficient_evidence": "证据不足",
    "not_checked": "未检查",
    "blocked": "受阻/待补材料",
    "failed": "不通过",
    "non_compliant": "不符合",
    "nonconforming": "不合格",
    "open": "待处理",
    "pending": "待处理",
    "closed": "已关闭",
    "resolved": "已解决",
}

SEVERITY_LABELS_ZH: dict[str, str] = {
    "critical": "重大问题",
    "blocker": "重大问题",
    "major": "主要问题",
    "high": "主要问题",
    "minor": "一般问题",
    "medium": "一般问题",
    "suggestion": "建议项",
    "info": "建议项",
    "low": "建议项",
    "pending_expert": "待专家确认",
}

WORK_ITEM_STATUS_LABELS_ZH: dict[str, str] = {
    "open": "待处理",
    "closed": "已关闭",
    "resolved": "已解决",
    "pending": "待处理",
    "in_progress": "处理中",
    "completed": "已完成",
    "failed": "失败",
    "blocked": "受阻",
}

EVIDENCE_STATUS_LABELS_ZH: dict[str, str] = {
    "supported": "已印证",
    "verified": "已印证",
    "evidence_supported": "已印证",
    "missing": "待补证",
    "insufficient": "证据不足",
    "insufficient_evidence": "证据不足",
    "not_checked": "未检查",
    "blocked": "受阻",
    "pending": "待补证",
}

MATERIAL_INSUFFICIENT_RATIONALE_ZH = (
    "当前资料包不足以支撑完整 GNC 关键设计审查，系统仅完成可审范围内的结构、内容和局部专业检查。"
    "请先补齐关键设计说明、故障分析、算法验证矩阵等材料后再复审。"
)

_TEMPLATE_SIGNALS = (
    "模板",
    "结构",
    "章节",
    "缺项",
    "目录",
    "格式",
    "完整性",
    "report_completeness",
    "template",
    "structure",
    "section",
    "outline",
    "必填",
    "缺失章节",
)

_CROSS_DOC_SIGNALS = (
    "跨文档",
    "文文",
    "一致性冲突",
    "术语不一致",
    "指标冲突",
    "编号不一致",
    "约束冲突",
    "cross_document",
    "cross-doc",
    "inconsistency",
    "conflict",
    "版本不一致",
)

_CONTENT_CONFLICT_SIGNALS = (
    "数值冲突",
    "指标不一致",
    "约束不一致",
    "不满足",
    "不符合",
    "错误",
    "偏差",
)


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _text_blob(finding: dict[str, Any]) -> str:
    parts = [
        finding.get("title"),
        finding.get("description"),
        finding.get("reasoning"),
        finding.get("recommendation"),
        finding.get("category"),
        finding.get("finding_type"),
        finding.get("topic"),
        finding.get("check_item_id"),
        finding.get("agent_id"),
        finding.get("discipline"),
        finding.get("expert_role"),
    ]
    metadata = _as_dict(finding.get("metadata"))
    parts.extend(
        [
            metadata.get("category"),
            metadata.get("topic"),
            metadata.get("rule_category"),
            metadata.get("unit_key"),
        ]
    )
    return " ".join(str(part or "") for part in parts).lower()


def _has_signal(blob: str, signals: tuple[str, ...]) -> bool:
    return any(signal.lower() in blob for signal in signals)


def _contains_cjk(text: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in text)


def _is_raw_enum_token(text: str) -> bool:
    token = str(text or "").strip()
    return bool(token) and "_" in token and token.replace("_", "").isalnum() and token == token.lower()


def _is_likely_english_business_text(text: str) -> bool:
    blob = str(text or "").strip()
    if not blob or _contains_cjk(blob):
        return False
    if _is_raw_enum_token(blob):
        return False
    latin = sum(1 for char in blob if char.isascii() and char.isalpha())
    return latin >= 12


def _is_predominantly_english_text(text: str) -> bool:
    blob = str(text or "").strip()
    if not blob:
        return False
    latin = sum(1 for char in blob if char.isascii() and char.isalpha())
    cjk = sum(1 for char in blob if "\u4e00" <= char <= "\u9fff")
    if latin >= 12 and latin > cjk * 2:
        return True
    return _is_likely_english_business_text(blob)


def resolve_verdict_label_zh(verdict: str = "") -> str:
    normalized = str(verdict or "").strip()
    if not normalized:
        return "待确认"
    key = normalized.lower()
    if key in VERDICT_LABELS_ZH:
        return VERDICT_LABELS_ZH[key]
    if _contains_cjk(normalized):
        return normalized
    if _is_raw_enum_token(normalized):
        return "待确认"
    return normalized


def localize_conclusion_text(text: str = "") -> str:
    """Return Chinese business wording when *text* is a raw verdict enum token."""
    blob = str(text or "").strip()
    if not blob:
        return ""
    key = blob.lower()
    if key in VERDICT_LABELS_ZH:
        return VERDICT_LABELS_ZH[key]
    return blob


_CONCLUSION_VERDICT_LINE_RE = re.compile(
    r"(?P<prefix>结论[：:]\s*)(?P<verdict>[A-Za-z][A-Za-z0-9_]*)\b"
)


def localize_report_markdown(markdown: str = "") -> str:
    """Replace bare verdict enum tokens after ``结论：`` anywhere in user markdown."""
    text = str(markdown or "")
    if not text.strip():
        return text

    def _replace(match: re.Match[str]) -> str:
        prefix = match.group("prefix")
        token = match.group("verdict")
        localized = localize_conclusion_text(token)
        if localized != token:
            return f"{prefix}{localized}"
        mapped = resolve_verdict_label_zh(token)
        if mapped != token:
            return f"{prefix}{mapped}"
        return match.group(0)

    return _CONCLUSION_VERDICT_LINE_RE.sub(_replace, text)


_SATISFIED_JUDGMENTS = frozenset({"satisfied", "passed", "pass", "compliant"})
_NOT_SATISFIED_JUDGMENTS = frozenset(
    {"not_satisfied", "failed", "fail", "non_compliant", "nonconforming", "rejected", "reject"}
)
_INSUFFICIENT_JUDGMENTS = frozenset({"insufficient_evidence", "insufficient"})
_NOT_CHECKED_JUDGMENTS = frozenset({"not_checked", "blocked", "pending"})


def summarize_judgment_stats(
    findings: list[dict[str, Any]],
    *,
    total_check_items: int = 0,
) -> dict[str, int]:
    """Count 符合/不符合/证据不足 using normalized judgment fields."""
    satisfied = not_satisfied = insufficient = not_checked = 0
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        judgment = _judgment(finding)
        if judgment in _SATISFIED_JUDGMENTS:
            satisfied += 1
        elif judgment in _NOT_SATISFIED_JUDGMENTS:
            not_satisfied += 1
        elif judgment in _INSUFFICIENT_JUDGMENTS:
            insufficient += 1
        elif judgment in _NOT_CHECKED_JUDGMENTS:
            not_checked += 1

    issue_count = not_satisfied + insufficient + not_checked
    total = max(int(total_check_items or 0), len(findings), issue_count + satisfied)
    if int(total_check_items or 0) > len(findings):
        satisfied = max(satisfied, total - issue_count)
    return {
        "total": total,
        "satisfied": satisfied,
        "not_satisfied": not_satisfied,
        "insufficient": insufficient,
        "not_checked": not_checked,
    }


def resolve_judgment_label_zh(judgment: str = "") -> str:
    normalized = str(judgment or "").strip()
    if not normalized:
        return ""
    key = normalized.lower()
    if key in JUDGMENT_LABELS_ZH:
        return JUDGMENT_LABELS_ZH[key]
    if key in BUSINESS_BUCKET_LABELS:
        return BUSINESS_BUCKET_LABELS[key]
    if _contains_cjk(normalized):
        return normalized
    if _is_raw_enum_token(normalized):
        return JUDGMENT_LABELS_ZH.get(key, "待确认")
    return normalized


def resolve_evidence_status_label_zh(status: str = "") -> str:
    normalized = str(status or "").strip()
    if not normalized:
        return ""
    key = normalized.lower()
    if key in EVIDENCE_STATUS_LABELS_ZH:
        return EVIDENCE_STATUS_LABELS_ZH[key]
    if _contains_cjk(normalized):
        return normalized
    if _is_raw_enum_token(normalized):
        return EVIDENCE_STATUS_LABELS_ZH.get(key, "待补证")
    return normalized


def resolve_severity_label_zh(severity: str = "") -> str:
    normalized = str(severity or "").strip()
    if not normalized:
        return ""
    key = normalized.lower()
    if key in SEVERITY_LABELS_ZH:
        return SEVERITY_LABELS_ZH[key]
    if _contains_cjk(normalized):
        return normalized
    if _is_raw_enum_token(normalized):
        return SEVERITY_LABELS_ZH.get(key, "待确认")
    return normalized


def resolve_work_item_status_label_zh(status: str = "") -> str:
    normalized = str(status or "").strip()
    if not normalized:
        return ""
    key = normalized.lower()
    if key in WORK_ITEM_STATUS_LABELS_ZH:
        return WORK_ITEM_STATUS_LABELS_ZH[key]
    if key in JUDGMENT_LABELS_ZH:
        return JUDGMENT_LABELS_ZH[key]
    if _contains_cjk(normalized):
        return normalized
    if _is_raw_enum_token(normalized):
        return WORK_ITEM_STATUS_LABELS_ZH.get(key, "待确认")
    return normalized


def resolve_agent_display_name(agent_id: str = "") -> tuple[str, str]:
    """Return (display_label, raw_id_for_secondary)."""
    raw = str(agent_id or "").strip()
    if not raw:
        return "专业审查项", ""
    if _contains_cjk(raw):
        return raw, ""
    if _is_raw_enum_token(raw) or _is_likely_english_business_text(raw):
        return "专业审查项", raw
    return raw, ""


def resolve_check_item_title(title: str = "", *, bucket: str = "") -> str:
    text = str(title or "").strip()
    if not text:
        return "审查项"
    if _contains_cjk(text):
        return text
    if _is_likely_english_business_text(text):
        if bucket == "insufficient_evidence":
            return "该检查项需补充材料后确认"
        return "该检查项待进一步确认"
    if _is_raw_enum_token(text):
        return "审查项"
    return text


def derive_rationale_zh(
    *,
    buckets: dict[str, int] | None = None,
    verdict: str = "",
    rationale: str = "",
    material_insufficiency: bool = False,
) -> str:
    rationale_text = str(rationale or "").strip()
    if (
        rationale_text
        and _contains_cjk(rationale_text)
        and not _is_likely_english_business_text(rationale_text)
        and not _is_predominantly_english_text(rationale_text)
    ):
        return rationale_text

    if material_insufficiency or str(verdict or "").strip().lower() in {
        MATERIAL_INSUFFICIENT_VERDICT,
        "conditional_rejection",
        "conditionally_rejected",
        "insufficient_materials",
        "blocked",
    }:
        return MATERIAL_INSUFFICIENT_RATIONALE_ZH

    bucket_map = buckets or {}
    if bucket_map.get("severe_error"):
        return "存在严重错误或关键风险，建议暂停放行并优先整改后再复审。"
    if bucket_map.get("cross_document_inconsistency"):
        return "发现跨文档术语、指标或约束不一致，需对齐任务书、需求与报告后再复审。"
    if bucket_map.get("template_structure_nonconforming"):
        return "模板或文档结构存在缺项/不合格，需先补齐结构与必填章节后再复审。"
    if bucket_map.get("content_nonconforming"):
        return "存在内容不合格项，需按专业意见完成整改并补充支撑材料。"
    if bucket_map.get("insufficient_evidence"):
        return "部分审查点证据不足，需补充材料后复审（不代表设计不通过）。"
    if bucket_map.get("manual_review"):
        return "部分审查点仍需人工确认，请结合原文证据与专业意见复核。"
    if bucket_map.get("verified") and not any(bucket_map.get(k) for k in BUSINESS_BUCKET_KEYS[:-1]):
        return "审查点已印证，可按流程进入下一环节。"
    return "审查已完成，请查看分桶明细与优先整改项。"


def _judgment(finding: dict[str, Any]) -> str:
    return str(
        finding.get("judgment")
        or finding.get("status")
        or finding.get("execution_status")
        or ""
    ).strip().lower()


def _severity(finding: dict[str, Any]) -> str:
    return str(finding.get("severity") or "").strip().lower()


def _has_evidence(finding: dict[str, Any]) -> bool:
    if finding.get("evidence_ids") or finding.get("source_quotes") or finding.get("quote"):
        return True
    refs = finding.get("evidence_refs") or finding.get("subject_evidence_refs") or finding.get("task_book_evidence_refs")
    return bool(refs)


def infer_evidence_gap_reason(finding: dict[str, Any]) -> str:
    for key in ("evidence_gap_reason", "missing_reason", "gap_reason", "evidence_gap"):
        text = str(finding.get(key) or "").strip()
        if text:
            return text
    metadata = _as_dict(finding.get("metadata"))
    for key in ("evidence_gap_reason", "missing_reason", "gap_reason"):
        text = str(metadata.get(key) or "").strip()
        if text:
            return text
    reasoning = str(finding.get("reasoning") or finding.get("description") or "").strip()
    if reasoning and len(reasoning) >= 12 and "证据" in reasoning:
        return reasoning
    return DEFAULT_INSUFFICIENT_REASON


def is_template_structure_issue(finding: dict[str, Any], *, review_mode: ReviewMode = "generic") -> bool:
    blob = _text_blob(finding)
    if _has_signal(blob, _TEMPLATE_SIGNALS):
        return True
    category = str(finding.get("category") or _as_dict(finding.get("metadata")).get("category") or "").lower()
    if category in {"template", "structure", "format", "completeness"}:
        return True
    unit_key = str(_as_dict(finding.get("metadata")).get("unit_key") or finding.get("unit_key") or "").lower()
    if "report_completeness" in unit_key or "completeness" in unit_key:
        return True
    if review_mode == "gnc" and _has_signal(blob, ("送审", "输入要求", "材料包", "cdr")):
        return True
    return False


def is_cross_document_issue(finding: dict[str, Any]) -> bool:
    blob = _text_blob(finding)
    if _has_signal(blob, _CROSS_DOC_SIGNALS):
        return True
    item_type = str(finding.get("item_type") or finding.get("conflict_type") or "").lower()
    return item_type.startswith("cross") or "conflict" in item_type


def is_content_conflict_issue(finding: dict[str, Any]) -> bool:
    judgment = _judgment(finding)
    if judgment in {"not_satisfied", "failed", "non_compliant", "nonconforming"}:
        if is_template_structure_issue(finding) or is_cross_document_issue(finding):
            return False
        blob = _text_blob(finding)
        if _has_signal(blob, _CONTENT_CONFLICT_SIGNALS):
            return True
        if _severity(finding) in {"major", "critical", "high"}:
            return True
    return False


def classify_finding(
    finding: dict[str, Any],
    *,
    review_mode: ReviewMode = "generic",
    force_cross_doc: bool = False,
) -> tuple[str, str]:
    """Return (business_bucket, reason_hint)."""
    judgment = _judgment(finding)
    severity = _severity(finding)
    blob = _text_blob(finding)

    if force_cross_doc or (is_cross_document_issue(finding) and judgment != "satisfied"):
        reason = str(finding.get("reasoning") or finding.get("description") or finding.get("summary") or "").strip()
        return "cross_document_inconsistency", reason or "跨文档术语/指标/约束存在不一致。"

    if severity in {"critical", "blocker"} or finding.get("hard_fail"):
        return "severe_error", str(finding.get("title") or finding.get("description") or "")

    if is_template_structure_issue(finding, review_mode=review_mode):
        return "template_structure_nonconforming", str(
            finding.get("reasoning") or finding.get("description") or finding.get("title") or ""
        )

    if judgment in {"satisfied", "passed", "compliant"} or (
        judgment not in {"not_satisfied", "insufficient_evidence", "not_checked", "blocked", "failed"}
        and _has_evidence(finding)
    ):
        return "verified", "审查点已有可追溯证据支撑。"

    if finding.get("requires_human_confirmation") or judgment in {"not_checked", "blocked"}:
        if judgment == "insufficient_evidence":
            pass
        else:
            reason = str(finding.get("reasoning") or finding.get("description") or "").strip()
            return "manual_review", reason or "需人工复核确认。"

    if is_content_conflict_issue(finding) or judgment in {"not_satisfied", "failed", "non_compliant", "nonconforming"}:
        if severity in {"major", "high"} and not is_template_structure_issue(finding, review_mode=review_mode):
            return "content_nonconforming", str(
                finding.get("reasoning") or finding.get("description") or finding.get("title") or ""
            )
        if judgment in {"not_satisfied", "failed", "non_compliant", "nonconforming"}:
            return "content_nonconforming", str(
                finding.get("reasoning") or finding.get("description") or finding.get("title") or ""
            )

    if judgment == "insufficient_evidence":
        if is_template_structure_issue(finding, review_mode=review_mode):
            return "template_structure_nonconforming", str(
                finding.get("reasoning") or finding.get("description") or "模板/结构项不应归为证据不足。"
            )
        if is_cross_document_issue(finding) or _has_signal(blob, _CONTENT_CONFLICT_SIGNALS):
            return "cross_document_inconsistency", str(
                finding.get("reasoning") or finding.get("description") or "已发现冲突，应归为文文不一致/内容不合格。"
            )
        return "insufficient_evidence", infer_evidence_gap_reason(finding)

    if severity in {"major", "high"}:
        return "content_nonconforming", str(finding.get("title") or finding.get("description") or "")

    if _has_evidence(finding):
        return "verified", "审查点已有可追溯证据支撑。"

    return "manual_review", str(finding.get("reasoning") or finding.get("description") or "待进一步确认。")


def empty_issue_buckets() -> dict[str, int]:
    return {key: 0 for key in BUSINESS_BUCKET_KEYS}


PROBLEM_BUCKET_KEYS: tuple[str, ...] = tuple(key for key in BUSINESS_BUCKET_KEYS if key != "verified")


def _finding_dedupe_key(item: dict[str, Any], index: int) -> str:
    key = str(
        item.get("finding_id")
        or item.get("check_item_id")
        or item.get("review_item_id")
        or item.get("item_id")
        or item.get("id")
        or ""
    ).strip()
    if not key:
        key = f"{item.get('title') or item.get('description') or index}"
    return key


def dedupe_findings(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop duplicate finding rows by stable id/title key."""
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for index, item in enumerate(findings, start=1):
        if not isinstance(item, dict):
            continue
        key = _finding_dedupe_key(item, index)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def cross_doc_items_to_findings(cross_doc_items: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Normalize open cross-document rows into finding-shaped records."""
    findings: list[dict[str, Any]] = []
    for index, item in enumerate(cross_doc_items or [], start=1):
        if not isinstance(item, dict):
            continue
        status = str(item.get("status") or "open").lower()
        if status in {"closed", "resolved"}:
            continue
        raw_item_type = str(item.get("item_type") or item.get("conflict_type") or "cross_document_issue")
        item_type = (
            raw_item_type
            if raw_item_type.startswith("cross") or "conflict" in raw_item_type
            else f"cross_document_{raw_item_type}"
        )
        findings.append(
            {
                **item,
                "finding_id": str(
                    item.get("finding_id")
                    or item.get("review_item_id")
                    or item.get("item_id")
                    or item.get("id")
                    or item.get("cross_doc_id")
                    or f"XDC-{index}"
                ),
                "title": str(item.get("title") or item.get("summary") or item.get("description") or "跨文档问题"),
                "description": str(item.get("description") or item.get("summary") or ""),
                "judgment": str(item.get("judgment") or "not_satisfied"),
                "item_type": item_type,
                "category": str(item.get("category") or "cross_document"),
                "severity": str(item.get("severity") or "major"),
            }
        )
    return findings


def merge_findings_for_conclusion(
    findings: list[dict[str, Any]],
    cross_doc_items: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Merge specialist/checklist findings with open cross-doc rows, deduped once."""
    return dedupe_findings([*(findings or []), *cross_doc_items_to_findings(cross_doc_items)])


def count_problem_buckets(buckets: dict[str, int]) -> int:
    """Count non-verified bucket entries — must reconcile with overview problem_count."""
    return sum(int(buckets.get(key) or 0) for key in PROBLEM_BUCKET_KEYS)


def compute_workbench_issue_summary(
    findings: list[dict[str, Any]],
    *,
    review_mode: ReviewMode = "generic",
    cross_doc_items: list[dict[str, Any]] | None = None,
    total_check_items: int = 0,
    open_rid_count: int = 0,
) -> dict[str, Any]:
    """Single source for workbench metrics, buckets, and report overview counts."""
    merged = merge_findings_for_conclusion(findings, cross_doc_items)
    bucket_summary = summarize_issue_buckets(merged, review_mode=review_mode)
    buckets = bucket_summary["buckets"]
    problem_count = count_problem_buckets(buckets)
    classified_count = sum(int(value or 0) for value in buckets.values())
    manual_review = int(buckets.get("manual_review") or 0)
    check_item_count = max(int(total_check_items or 0), 0)
    return {
        "buckets": buckets,
        "bucket_labels": bucket_summary["bucket_labels"],
        "items": bucket_summary["items"],
        "merged_findings": merged,
        "problem_count": problem_count,
        "classified_count": classified_count,
        "check_item_count": check_item_count,
        "pending_confirm": manual_review + max(int(open_rid_count or 0), 0),
        "verified_count": int(buckets.get("verified") or 0),
    }


def summarize_issue_buckets(findings: list[dict[str, Any]], *, review_mode: ReviewMode = "generic") -> dict[str, Any]:
    buckets = empty_issue_buckets()
    items: list[dict[str, Any]] = []
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        bucket, reason = classify_finding(finding, review_mode=review_mode)
        buckets[bucket] = buckets.get(bucket, 0) + 1
        items.append(
            {
                **finding,
                "business_bucket": bucket,
                "business_bucket_label": BUSINESS_BUCKET_LABELS[bucket],
                "bucket_reason": reason,
                "missing_reason": infer_evidence_gap_reason(finding) if bucket == "insufficient_evidence" else "",
                "evidence_gap_reason": infer_evidence_gap_reason(finding) if bucket == "insufficient_evidence" else "",
            }
        )
    return {
        "buckets": buckets,
        "bucket_labels": dict(BUSINESS_BUCKET_LABELS),
        "items": items,
    }


def _priority_score(bucket: str, finding: dict[str, Any]) -> int:
    order = {
        "severe_error": 100,
        "content_nonconforming": 90,
        "template_structure_nonconforming": 85,
        "cross_document_inconsistency": 80,
        "insufficient_evidence": 50,
        "manual_review": 40,
        "verified": 0,
    }
    base = order.get(bucket, 0)
    severity = _severity(finding)
    if severity == "critical":
        base += 20
    elif severity == "major":
        base += 10
    return base


def build_priority_items(
    findings: list[dict[str, Any]],
    *,
    review_mode: ReviewMode = "generic",
    limit: int = 8,
    extra_items: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    ranked: list[tuple[int, dict[str, Any]]] = []
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        bucket, reason = classify_finding(finding, review_mode=review_mode)
        if bucket == "verified":
            continue
        ranked.append(
            (
                _priority_score(bucket, finding),
                {
                    "id": str(finding.get("finding_id") or finding.get("check_item_id") or finding.get("id") or ""),
                    "title": str(finding.get("title") or finding.get("description") or "审查项"),
                    "business_bucket": bucket,
                    "business_bucket_label": BUSINESS_BUCKET_LABELS[bucket],
                    "severity": finding.get("severity") or "",
                    "judgment": finding.get("judgment") or "",
                    "reason": reason,
                    "missing_reason": infer_evidence_gap_reason(finding) if bucket == "insufficient_evidence" else "",
                    "recommendation": finding.get("recommendation") or "",
                    "tab_hint": _tab_hint_for_bucket(bucket),
                },
            )
        )
    for item in extra_items or []:
        if not isinstance(item, dict):
            continue
        bucket = str(item.get("business_bucket") or "manual_review")
        ranked.append((_priority_score(bucket, item), item))

    ranked.sort(key=lambda pair: pair[0], reverse=True)
    return [item for _, item in ranked[:limit]]


def _tab_hint_for_bucket(bucket: str) -> str:
    return {
        "severe_error": "findings",
        "content_nonconforming": "findings",
        "template_structure_nonconforming": "check_items",
        "cross_document_inconsistency": "cross_doc",
        "insufficient_evidence": "findings",
        "manual_review": "decision",
        "verified": "coverage",
    }.get(bucket, "findings")


def build_coverage_summary(
    *,
    total_check_items: int = 0,
    verified_count: int = 0,
    evidence_count: int = 0,
    document_type_label: str = "",
    notes: list[str] | None = None,
) -> dict[str, Any]:
    checked = max(total_check_items, 0)
    verified = max(verified_count, 0)
    rate = round(verified / checked, 3) if checked else None
    return {
        "total_check_items": checked,
        "verified_count": verified,
        "evidence_count": evidence_count,
        "coverage_rate": rate,
        "document_type_label": document_type_label,
        "notes": list(notes or []),
    }


def resolve_review_scope_label(
    *,
    review_mode: ReviewMode,
    explicit_scope: str = "",
    materials: list[dict[str, Any]] | None = None,
    scenario: str = "",
    limited_scope: list[str] | None = None,
) -> dict[str, Any]:
    scope_parts: list[str] = []
    if explicit_scope.strip():
        scope_parts.append(explicit_scope.strip())
    if scenario.strip():
        scope_parts.append(scenario.strip())

    doc_types: list[str] = []
    material_names: list[str] = []
    material_summary_lines: list[str] = []
    unknown_roles = 0
    for material in materials or []:
        if not isinstance(material, dict):
            continue
        name = str(material.get("name") or material.get("file_name") or "").strip()
        role = str(material.get("role") or material.get("document_type") or "").strip()
        if name and name not in material_names:
            material_names.append(name)
            if role.lower() in {"", "unknown", "未识别"}:
                material_summary_lines.append(name)
            else:
                material_summary_lines.append(f"{name}（{role}）")
        if role.lower() in {"", "unknown", "未识别"}:
            unknown_roles += 1
        elif role not in doc_types:
            doc_types.append(role)

    mode_labels = {
        "gnc": "GNC 专业审查 + 模板审查（结构/模板完整性、专业技术内容）",
        "review_plus": "通用审查（结构正确性 + 内容正确性 + 跨文档一致性）",
        "super_agent": "智能审查（按路由执行 GNC 或通用/专家委员会）",
        "generic": "通用审查",
    }
    actual: list[str] = [mode_labels.get(review_mode, mode_labels["generic"])]
    if doc_types:
        actual.append(f"材料类型：{', '.join(doc_types[:6])}")
    if unknown_roles:
        actual.append("文档类型待确认")
    if limited_scope:
        actual.append(f"受限范围：{'; '.join(str(x) for x in limited_scope[:4])}")

    plan_lines = [actual[0]] if actual else []
    if scenario.strip() and scenario.strip() not in plan_lines:
        plan_lines.append(f"审查场景：{scenario.strip()}")
    if explicit_scope.strip() and explicit_scope.strip() not in plan_lines:
        plan_lines.append(f"范围说明：{explicit_scope.strip()}")

    return {
        "review_mode": review_mode,
        "review_mode_label": {
            "gnc": "GNC 审查",
            "review_plus": "通用审查",
            "super_agent": "智能审查",
            "generic": "通用审查",
        }.get(review_mode, "审查"),
        "explicit_scope": explicit_scope,
        "actual_scope": actual,
        "document_type_pending": unknown_roles > 0,
        "material_names": material_names,
        "material_summary_lines": material_summary_lines,
        "material_count": len(material_names),
        "review_plan_lines": plan_lines,
    }


def detect_material_insufficiency(
    *,
    verdict: str = "",
    rationale: str = "",
    findings: list[dict[str, Any]] | None = None,
    discipline_reviews: dict[str, Any] | None = None,
    slot_status: dict[str, Any] | None = None,
) -> bool:
    gnc_chief = _as_dict((discipline_reviews or {}).get("gnc_chief_reviewer"))
    chief_verdict = str(gnc_chief.get("verdict") or "").strip().lower()
    if chief_verdict and any(marker.lower() in chief_verdict for marker in _SUSPEND_REVIEW_MARKERS):
        return True

    slots = _as_dict(slot_status)
    missing_slots = _as_list(slots.get("missing_slots"))
    review_plus_ready = slots.get("review_plus_ready")
    normalized_verdict = str(verdict or "").strip().lower()
    if review_plus_ready is False and missing_slots and normalized_verdict in _REJECTED_VERDICTS:
        return True

    blocked = 0
    for finding in findings or []:
        if not isinstance(finding, dict):
            continue
        blob = _text_blob(finding)
        if any(marker.lower() in blob for marker in _BLOCKED_EVIDENCE_MARKERS):
            blocked += 1
    if blocked >= max(3, int(len(findings or []) * 0.25)):
        return True

    rationale_blob = str(rationale or "").lower()
    if normalized_verdict in _REJECTED_VERDICTS and any(
        marker.lower() in rationale_blob for marker in _BLOCKED_EVIDENCE_MARKERS
    ):
        return True
    return False


def resolve_material_insufficiency_conclusion(
    *,
    verdict: str,
    rationale: str,
    findings: list[dict[str, Any]],
    buckets: dict[str, int],
    discipline_reviews: dict[str, Any] | None = None,
    slot_status: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if not detect_material_insufficiency(
        verdict=verdict,
        rationale=rationale,
        findings=findings,
        discipline_reviews=discipline_reviews,
        slot_status=slot_status,
    ):
        return None

    missing_slots = [str(item) for item in _as_list(_as_dict(slot_status).get("missing_slots")) if item]
    scope_notes: list[str] = []
    if missing_slots:
        scope_notes.append(f"缺失材料槽位：{'、'.join(missing_slots[:6])}")
    scope_notes.append("当前为材料/规则不足导致无法完整 GNC 审查，请勿等同于设计层面的有条件否决。")

    headline = MATERIAL_INSUFFICIENT_HEADLINE
    insufficient_count = int(buckets.get("insufficient_evidence") or 0)
    if insufficient_count >= max(3, len(findings) // 2):
        headline = "材料不足，大量审查点无法印证，请先补齐材料与审查规则"

    return {
        "verdict": MATERIAL_INSUFFICIENT_VERDICT,
        "headline_verdict": headline,
        "one_line_conclusion": headline,
        "material_insufficiency": True,
        "scope_notes": scope_notes,
        "coverage_notes": [
            "本次结论因上传材料或审查规则不足产生，不代表设计内容已被有条件否决。",
        ],
    }


def build_one_line_conclusion(buckets: dict[str, int], verdict: str = "") -> str:
    safe_verdict = verdict if _contains_cjk(str(verdict or "")) and not _is_likely_english_business_text(verdict) else ""
    if buckets.get("severe_error"):
        return safe_verdict or "存在严重错误，建议暂停放行并优先整改。"
    if buckets.get("cross_document_inconsistency"):
        return safe_verdict or "存在文文不一致，需对齐需求/任务书/跨文档指标与约束。"
    if buckets.get("template_structure_nonconforming"):
        return safe_verdict or "模板或文档结构不合格，需先补齐结构与模板项。"
    if buckets.get("content_nonconforming"):
        return safe_verdict or "存在内容不合格项，需按专业意见整改。"
    if buckets.get("insufficient_evidence"):
        return safe_verdict or "部分审查点证据不足，需补充材料后复审（非失败兜底）。"
    if buckets.get("manual_review"):
        return safe_verdict or "部分项待人工确认。"
    if buckets.get("verified") and not any(buckets.get(k) for k in BUSINESS_BUCKET_KEYS[:-1]):
        return safe_verdict or "审查点已印证，可按流程进入下一环节。"
    return safe_verdict or "审查已完成，请查看分桶明细与优先整改项。"


def build_conclusion_payload(
    *,
    review_mode: ReviewMode,
    verdict: str = "",
    rationale: str = "",
    findings: list[dict[str, Any]],
    cross_doc_items: list[dict[str, Any]] | None = None,
    materials: list[dict[str, Any]] | None = None,
    explicit_scope: str = "",
    scenario: str = "",
    total_check_items: int = 0,
    evidence_count: int = 0,
    limited_scope: list[str] | None = None,
    extra_priority: list[dict[str, Any]] | None = None,
    discipline_reviews: dict[str, Any] | None = None,
    slot_status: dict[str, Any] | None = None,
) -> dict[str, Any]:
    merged_findings = merge_findings_for_conclusion(findings, cross_doc_items)
    summary = summarize_issue_buckets(merged_findings, review_mode=review_mode)
    buckets = summary["buckets"]
    problem_count = count_problem_buckets(buckets)
    classified_count = sum(int(value or 0) for value in buckets.values())
    review_scope = resolve_review_scope_label(
        review_mode=review_mode,
        explicit_scope=explicit_scope,
        materials=materials,
        scenario=scenario,
        limited_scope=limited_scope,
    )
    priority_items = build_priority_items(
        summary["items"],
        review_mode=review_mode,
        extra_items=extra_priority,
    )
    coverage_summary = build_coverage_summary(
        total_check_items=total_check_items or len(findings),
        verified_count=buckets.get("verified", 0),
        evidence_count=evidence_count,
        document_type_label="文档类型待确认" if review_scope.get("document_type_pending") else "",
        notes=[review_scope["actual_scope"][-1]] if review_scope.get("document_type_pending") else [],
    )
    resolved_verdict = verdict
    headline = build_one_line_conclusion(buckets, verdict=verdict)
    material_override = resolve_material_insufficiency_conclusion(
        verdict=verdict,
        rationale=rationale,
        findings=merged_findings,
        buckets=buckets,
        discipline_reviews=discipline_reviews,
        slot_status=slot_status,
    )
    if material_override:
        resolved_verdict = str(material_override["verdict"])
        headline = str(material_override["headline_verdict"])
        review_scope = {
            **review_scope,
            "material_insufficiency": True,
            "actual_scope": [
                *list(review_scope.get("actual_scope") or []),
                *list(material_override.get("scope_notes") or []),
            ],
        }
        coverage_summary = {
            **coverage_summary,
            "notes": [
                *list(coverage_summary.get("notes") or []),
                *list(material_override.get("coverage_notes") or []),
            ],
        }

    material_insufficiency = bool(material_override)
    verdict_label_zh = resolve_verdict_label_zh(resolved_verdict)
    rationale_zh = derive_rationale_zh(
        buckets=buckets,
        verdict=resolved_verdict,
        rationale=rationale,
        material_insufficiency=material_insufficiency,
    )

    payload = {
        "headline_verdict": headline,
        "headline_zh": headline,
        "one_line_conclusion": headline,
        "verdict": resolved_verdict,
        "verdict_label_zh": verdict_label_zh,
        "rationale": rationale,
        "rationale_zh": rationale_zh,
        "issue_buckets": buckets,
        "bucket_labels": summary["bucket_labels"],
        "issue_summary": {
            "buckets": buckets,
            "bucket_labels": summary["bucket_labels"],
            "problem_count": problem_count,
            "classified_count": classified_count,
            "check_item_count": max(int(total_check_items or 0), len(findings)),
            "pending_confirm": int(buckets.get("manual_review") or 0),
        },
        "review_scope": review_scope,
        "priority_items": priority_items,
        "coverage_summary": coverage_summary,
        "classified_findings": summary["items"],
    }
    if material_override:
        payload["material_insufficiency"] = True
    return payload
