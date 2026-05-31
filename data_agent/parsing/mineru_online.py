"""Shared MinerU online parse chain (Agent + v4 extract) with fallback tracing."""

from __future__ import annotations

import logging
from time import perf_counter

from data_agent.parsing.fallback_trace import record_parser_fallback
from data_agent.parsing.mineru_config import (
    describe_online_route,
    log_online_route_decision,
    mineru_agent_enabled,
    mineru_extract_available,
    resolve_online_parse_order,
)
from data_agent.parsing.schemas import ParsedDocument

logger = logging.getLogger(__name__)


def _online_parse_succeeded(parsed_doc: ParsedDocument) -> bool:
    return parsed_doc.parse_status != "failed" and bool(parsed_doc.blocks)


def attempt_mineru_online(
    file_path: str,
    file_name: str,
    parsed_doc: ParsedDocument,
) -> bool:
    """Run MinerU online APIs per env routing. Returns True when blocks are produced."""
    from data_agent.parsing.parsers.mineru_agent_parser import (
        mineru_agent_supports,
        parse_via_mineru_agent,
    )
    from data_agent.parsing.parsers.mineru_extract_parser import (
        mineru_extract_supports,
        parse_via_mineru_extract,
    )

    logs = parsed_doc.parser_fallback_logs
    order = resolve_online_parse_order(file_path, file_name)
    log_online_route_decision(file_path, file_name, context=file_name)

    if not order:
        if mineru_agent_supports(file_name) and not mineru_agent_enabled():
            parsed_doc.warnings.append(
                "MinerU Agent 未启用（MINERU_AGENT_API_ENABLED=0 或 MINERU_API_MODE=extract/disabled）。"
            )
            record_parser_fallback(
                logs,
                source_parser="mineru_agent",
                fallback_parser="mineru_extract",
                reason="agent_disabled",
                recovered=False,
            )
        if mineru_extract_supports(file_name) and not mineru_extract_available():
            parsed_doc.warnings.append(
                "MinerU v4 精准解析未启用（需 MINERU_AGENT_API_TOKEN 且 MINERU_EXTRACT_API_ENABLED≠0）。"
            )
        return False

    attempted: list[str] = []
    for index, route in enumerate(order):
        next_route = order[index + 1] if index + 1 < len(order) else "mineru_local"
        if route == "extract":
            if not mineru_extract_supports(file_name):
                continue
            if not mineru_extract_available():
                parsed_doc.warnings.append(
                    "MinerU v4 精准解析未启用（需 MINERU_AGENT_API_TOKEN 且 MINERU_EXTRACT_API_ENABLED≠0）。"
                )
                continue
            start = perf_counter()
            parse_via_mineru_extract(file_path, file_name, parsed_doc)
            elapsed_ms = int((perf_counter() - start) * 1000)
            attempted.append("extract")
            if _online_parse_succeeded(parsed_doc):
                logger.info(
                    "[MinerU] v4 extract succeeded (%s)",
                    describe_online_route(file_path, file_name),
                )
                return True
            record_parser_fallback(
                logs,
                source_parser="mineru_extract",
                fallback_parser=next_route if next_route != "mineru_local" else "mineru_local",
                reason="extract_failed_or_empty",
                recovered=False,
                elapsed_ms=elapsed_ms,
            )
            parsed_doc.warnings.append("MinerU v4 精准解析失败或结果为空，尝试下一档 MinerU API。")
            parsed_doc.blocks = []
            parsed_doc.parse_status = "ok"
            continue

        if route == "agent":
            if not mineru_agent_supports(file_name):
                continue
            if not mineru_agent_enabled():
                parsed_doc.warnings.append(
                    "MinerU Agent 未启用（请检查 MINERU_AGENT_API_ENABLED / MINERU_API_MODE）。"
                )
                record_parser_fallback(
                    logs,
                    source_parser="mineru_agent",
                    fallback_parser=next_route,
                    reason="agent_disabled",
                    recovered=False,
                )
                continue
            start = perf_counter()
            parse_via_mineru_agent(file_path, file_name, parsed_doc)
            elapsed_ms = int((perf_counter() - start) * 1000)
            attempted.append("agent")
            if _online_parse_succeeded(parsed_doc):
                logger.info(
                    "[MinerU] Agent succeeded (%s)",
                    describe_online_route(file_path, file_name),
                )
                return True
            record_parser_fallback(
                logs,
                source_parser="mineru_agent",
                fallback_parser=next_route,
                reason="agent_failed_or_empty",
                recovered=False,
                elapsed_ms=elapsed_ms,
            )
            parsed_doc.warnings.append("MinerU Agent 解析失败或结果为空，尝试下一档 MinerU API。")
            parsed_doc.blocks = []
            parsed_doc.parse_status = "ok"

    if attempted:
        logger.warning(
            "[MinerU] online chain exhausted (%s); attempted=%s",
            describe_online_route(file_path, file_name),
            attempted,
        )
    return False


__all__ = ["attempt_mineru_online"]
