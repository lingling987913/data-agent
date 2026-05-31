"""LLM-assisted parse rationality calibration."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import Any, Callable

from data_agent.agents.format_guard import llm_client
from data_agent.agents.parse_calibrator.rules import build_calibration_contexts
from data_agent.agents.parse_calibrator.schemas import CalibrationContext, block_context_text
from data_agent.parsing.schemas import ParsedDocument, ParseCalibrationRecord

logger = logging.getLogger(__name__)

DEFAULT_CALIBRATION_SYSTEM = (
    "你是工程文档解析合理性校准智能体。"
    "你的任务是根据同页和前后文判断 OCR/解析结果是否明显不合理。"
    "只标记可疑结果并给出人工复核建议，禁止臆造真实测量值，禁止要求自动改写原文。"
    "重点关注直径符号 Φ/φ 的 OCR 误识别：当字段名或上下文包含外径、内径、直径、孔径、轴径、转子、定子等词，"
    "且同一行或相邻上下文存在 Φ150、Φ100.5 等直径基准时，实测值中形如 4150、4100.58、4 100.5、415003、+150.03、###.58 的值应重点复核。"
    "这类值可能同时存在符号错误和小数点丢失，例如 4100.58 可能表示 Φ100.58，415003 在 Φ150 语境下可能表示 Φ150.03，"
    "+150.03 或 ＋150.03 可能表示 Φ150.03。遇到 ###.58、##.58 等乱码占位符时，只能判断为 OCR 严重损坏并要求人工复核，"
    "除非上下文直接给出可恢复证据，否则不要臆造为 Φ150.08 等确定值。"
    "遇到这类情况应返回 issue_type=symbol_confusion、status=needs_review，并在 suggested_text 中给出完整文本级建议，"
    "同时 evidence 同时包含上下文基准、原始可疑值以及建议值或复核说明。"
    "产品序号/型号前缀一致性：当同文档多次出现形如 4H-2335-xx 的 H 系列序号时，应将其视为型号前缀共识；"
    "若个别块出现 LH-2335-xx、1H-2335-xx 等与多数前缀仅差 OCR 易混字符（如 L/4、I/1、O/0），"
    "应判断为 symbol_confusion 并保留规则层建议的完整 suggested_text。"
    "只输出 JSON 对象，不要解释，不要代码围栏。"
)


class ParseRationalityCalibratorAgent:
    def __init__(
        self,
        *,
        model_id: str | None = None,
        context_window: int = 2,
        max_blocks: int = 50,
        enable_llm: bool = True,
        system_prompt: str | None = None,
    ) -> None:
        self.model_id = model_id
        self.context_window = max(0, context_window)
        self.max_blocks = max(0, max_blocks)
        self.enable_llm = enable_llm
        self._system_prompt = system_prompt or DEFAULT_CALIBRATION_SYSTEM

    async def calibrate_document(
        self,
        document: ParsedDocument,
        *,
        max_concurrency: int = 3,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> list[ParseCalibrationRecord]:
        if document.parse_status == "failed" or not document.blocks or self.max_blocks == 0:
            return []

        contexts = build_calibration_contexts(
            document.blocks,
            context_window=self.context_window,
            max_blocks=self.max_blocks,
        )
        if not contexts:
            return []

        if not self.enable_llm:
            return [ctx.heuristic_record for ctx in contexts if ctx.heuristic_record is not None]

        total = len(contexts)
        completed = 0
        progress_lock = asyncio.Lock()
        sem = asyncio.Semaphore(max(1, max_concurrency))

        async def _one(ctx: CalibrationContext, index: int) -> ParseCalibrationRecord | None:
            nonlocal completed
            async with sem:
                logger.debug("[ParseCalibrator] block %s/%s id=%s", index, total, ctx.block.block_id)
                record = await self._calibrate_one(ctx)
            async with progress_lock:
                completed += 1
                if progress_callback is not None:
                    progress_callback(completed, total)
            return record

        raw_records = await asyncio.gather(*[_one(ctx, i + 1) for i, ctx in enumerate(contexts)])
        records = [record for record in raw_records if record is not None]
        return _dedupe_records(records)

    def calibrate_document_sync(
        self,
        document: ParsedDocument,
        **kwargs: object,
    ) -> list[ParseCalibrationRecord]:
        def _run() -> list[ParseCalibrationRecord]:
            return asyncio.run(self.calibrate_document(document, **kwargs))  # type: ignore[arg-type]

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return _run()

        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(_run).result()

    async def _calibrate_one(self, ctx: CalibrationContext) -> ParseCalibrationRecord | None:
        started = time.perf_counter()
        fallback = ctx.heuristic_record
        model = self.model_id
        try:
            from data_agent.core.config import (
                get_parsing_calibration_llm_timeout,
                get_parsing_calibration_model,
                get_parsing_calibration_profile,
            )

            model = model or get_parsing_calibration_model()
            profile_role = get_parsing_calibration_profile()
            raw = await llm_client.complete_text(
                self._system_prompt,
                _build_user_prompt(ctx),
                model_id=model,
                temperature=0.0,
                max_tokens=1200,
                timeout_sec=float(get_parsing_calibration_llm_timeout()),
                profile_role=profile_role,
            )
            payload = _extract_json_object(raw)
            if not payload or not payload.get("is_issue"):
                if fallback is not None and _should_keep_heuristic_on_llm_reject(ctx):
                    fallback.model_id = model or ""
                    fallback.latency_ms = int((time.perf_counter() - started) * 1000)
                    return fallback
                return None
            record = _record_from_payload(ctx, payload)
            record.model_id = model or ""
            record.latency_ms = int((time.perf_counter() - started) * 1000)
            return record
        except llm_client.StructuringLLMError as exc:
            logger.info("[ParseCalibrator] LLM unavailable, using heuristic record: %s", exc)
        except Exception as exc:
            logger.warning("[ParseCalibrator] calibration failed for block %s: %s", ctx.block.block_id, exc)

        if fallback is not None:
            fallback.model_id = model or ""
            fallback.latency_ms = int((time.perf_counter() - started) * 1000)
        return fallback


def _should_keep_heuristic_on_llm_reject(ctx: CalibrationContext) -> bool:
    if ctx.heuristic_record is None:
        return False
    if ctx.issue_type in {"symbol_confusion", "numeric_outlier"} and ctx.evidence:
        return True
    return ctx.heuristic_record.confidence >= 0.8


def _build_user_prompt(ctx: CalibrationContext) -> str:
    fallback = ctx.heuristic_record.model_dump(mode="json") if ctx.heuristic_record else {}
    payload = {
        "block_id": ctx.block.block_id,
        "page_hint": ctx.block.page_hint,
        "block_confidence": ctx.block.confidence,
        "issue_type_hint": ctx.issue_type,
        "rule_reason": ctx.reason,
        "rule_evidence": ctx.evidence,
        "context": block_context_text(ctx),
        "heuristic_record": fallback,
    }
    return (
        "请判断当前块是否存在明显 OCR/解析合理性问题。"
        "如果只是可能但不确定，status 使用 needs_review；如果不是问题，返回 {\"is_issue\": false}。\n"
        "输入中的 heuristic_record 是规则层生成的高召回候选；请优先审批该候选是否合理。"
        "如果候选符合上下文，应返回 is_issue=true，并尽量保留候选 suggested_text/evidence，只润色 reason。"
        "如果候选不确定但仍可疑，也应返回 is_issue=true 且 status=needs_review；只有明显不是问题才返回 is_issue=false。\n"
        "直径符号审批规则：若上下文出现外径/内径/直径/孔径/轴径/转子/定子等字段，且附近有 Φ 或 φ 直径基准，"
        "则将以 4 开头且与基准尺寸接近的实测值视为疑似 Φ 被识别为 4；"
        "若数字紧凑无小数点，也要尝试按基准整数部分恢复小数点，例如 “电机定子外径 Φ150 415003” 应判断为 "
        "415003 疑似 Φ150.03，返回 symbol_confusion 和 needs_review，而不是返回 is_issue=false。"
        "若出现 “电机定子外径 Φ150 +150.03” 或 “电机定子外径 Φ150 ＋150.03”，应判断 +/＋ 疑似 Φ 的 OCR 误识别，"
        "建议复核为 Φ150.03。若出现 “电机定子外径 Φ150 ###.58”，应判断为直径符号或数字 OCR 严重损坏，"
        "返回 needs_review 并高亮 ###.58，但不要在证据不足时臆造为 Φ150.08。\n"
        "产品序号审批规则：若 heuristic_record 或上下文显示同文档 -2335- 等系列序号以 4H 等前缀重复出现，"
        "而当前块出现 LH 等仅首字符 OCR 易混的差异，应判断为 symbol_confusion 并保留建议将 LH 恢复为 4H 的 "
        "suggested_text，而不是返回 is_issue=false。\n"
        "若是问题，返回 JSON："
        "{\"is_issue\": true, \"issue_type\": \"numeric_outlier|symbol_confusion|unit_mismatch|context_conflict|other\", "
        "\"severity\": \"info|warning|critical\", \"suggested_text\": \"用于前端展示的完整文本，不能只写说明\", "
        "\"reason\": \"...\", \"evidence\": [\"...\"], \"confidence\": 0.0, \"status\": \"needs_review|suggested\"}。\n"
        f"{json.dumps(payload, ensure_ascii=False)}"
    )


def _extract_json_object(raw: str) -> dict[str, Any]:
    text = _strip_fences(raw or "")
    decoder = json.JSONDecoder()
    candidates: list[dict[str, Any]] = []
    for match in re.finditer(r"\{", text):
        try:
            loaded, _end = decoder.raw_decode(text[match.start() :])
        except json.JSONDecodeError:
            continue
        if isinstance(loaded, dict):
            candidates.append(loaded)
    return candidates[-1] if candidates else {}


def _strip_fences(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.IGNORECASE)
        stripped = re.sub(r"\s*```$", "", stripped)
    return stripped.strip()


def _record_from_payload(ctx: CalibrationContext, payload: dict[str, Any]) -> ParseCalibrationRecord:
    fallback = ctx.heuristic_record
    issue_type = str(payload.get("issue_type") or ctx.issue_type or "other")
    if issue_type not in {"numeric_outlier", "symbol_confusion", "unit_mismatch", "context_conflict", "other"}:
        issue_type = "other"
    severity = str(payload.get("severity") or (fallback.severity if fallback else "warning"))
    if severity not in {"info", "warning", "critical"}:
        severity = "warning"
    status = str(payload.get("status") or "needs_review")
    if status not in {"needs_review", "suggested"}:
        status = "needs_review"
    evidence = payload.get("evidence")
    if not isinstance(evidence, list):
        evidence = fallback.evidence if fallback else ctx.evidence
    confidence = _coerce_confidence(payload.get("confidence"), fallback.confidence if fallback else 0.0)
    suggested_text = str(payload.get("suggested_text") or (fallback.suggested_text if fallback else ""))
    if fallback and fallback.suggested_text and not _suggestion_preserves_fallback_terms(
        suggested_text,
        fallback.evidence,
    ):
        suggested_text = fallback.suggested_text
    return ParseCalibrationRecord(
        block_id=ctx.block.block_id,
        page_hint=ctx.block.page_hint,
        issue_type=issue_type,  # type: ignore[arg-type]
        severity=severity,  # type: ignore[arg-type]
        original_text=ctx.block.text,
        suggested_text=suggested_text,
        reason=str(payload.get("reason") or (fallback.reason if fallback else ctx.reason)),
        evidence=[str(item) for item in evidence],
        confidence=confidence,
        status=status,  # type: ignore[arg-type]
    )


def _suggestion_preserves_fallback_terms(suggested_text: str, fallback_evidence: list[str]) -> bool:
    replacement_terms = [
        fallback_evidence[index]
        for index in range(1, len(fallback_evidence), 2)
        if fallback_evidence[index].startswith("Φ")
    ]
    review_terms = [
        fallback_evidence[index]
        for index in range(1, len(fallback_evidence), 2)
        if fallback_evidence[index].startswith(("###", "＃＃＃", "##", "＃＃"))
    ]
    required_terms = replacement_terms + review_terms
    return all(term in suggested_text for term in required_terms)


def _coerce_confidence(value: object, default: float) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        confidence = float(default)
    return max(0.0, min(1.0, confidence))


def _dedupe_records(records: list[ParseCalibrationRecord]) -> list[ParseCalibrationRecord]:
    deduped: list[ParseCalibrationRecord] = []
    seen: set[tuple[str, str, str]] = set()
    for record in records:
        key = (record.block_id, record.issue_type, record.reason)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(record)
    return deduped
