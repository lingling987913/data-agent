"""LLM-based semantic section tree construction."""

from __future__ import annotations

import logging
import os
import re
import uuid

from data_agent.parsing.schemas import (
    DocumentSection,
    DocumentSectionTree,
    DocumentTocEntry,
    ParsedDocument,
    ParsedDocumentBlock,
)
from data_agent.parsing.structuring.section_tree import (
    _attach_toc_matches,
    _prepare_doc_for_chunking,
    build_section_tree,
)

logger = logging.getLogger(__name__)


class SemanticChunkOutput:
    """LLM 语义切分输出 — 用于 output_schema 约束"""
    pass

def _fine_split_to_paragraphs(parsed_doc: ParsedDocument, max_chars: int = 400) -> list[ParsedDocumentBlock]:
    """
    将解析后的 blocks 进一步拆分成细粒度段落（约 max_chars 字/段），
    作为 LLM 语义边界合并的输入。
    保留 block_type / block_id 元信息。
    """
    result: list[ParsedDocumentBlock] = []
    for block in parsed_doc.blocks:
        if not block.text.strip():
            continue
        if len(block.text) <= max_chars or block.block_type == "heading":
            result.append(block)
            continue
        # 按句号/换行拆分
        sentences = re.split(r'(?<=[。！？\n])', block.text)
        buf: list[str] = []
        buf_len = 0
        for sent in sentences:
            if buf_len + len(sent) > max_chars and buf:
                text = "".join(buf).strip()
                if text:
                    result.append(ParsedDocumentBlock(
                        block_id=str(uuid.uuid4()),
                        block_type=block.block_type,
                        text=text,
                        level=block.level,
                        order_index=len(result),
                    ))
                buf = [sent]
                buf_len = len(sent)
            else:
                buf.append(sent)
                buf_len += len(sent)
        if buf:
            text = "".join(buf).strip()
            if text:
                result.append(ParsedDocumentBlock(
                    block_id=str(uuid.uuid4()),
                    block_type=block.block_type,
                    text=text,
                    level=block.level,
                    order_index=len(result),
                ))
    return result


async def _run_batch_async(
    batch_no: int,
    batch: list[ParsedDocumentBlock],
    global_offset: int,
    step: int,
    model_config: dict,
    total_batches: int,
    semaphore: "_asyncio.Semaphore | None" = None,
) -> list[dict]:
    """
    单个滑动窗口批次：使用 openai SDK 直接流式调用 LLM。

    为什么不用 Agno Agent？
      - Agent.run(stream=None) 走非流式路径 → model.invoke()
      - invoke() 内部没有显式传 stream=False，若 request_params 含 stream=True
        则返回类型变成 Stream iterator，与 _parse_provider_response 期望的
        ChatCompletion 对象冲突
      - 切片任务是纯一次性 JSON 补全，无工具/记忆/多轮，直接用 SDK 更可控
    """
    import json as _json
    import asyncio as _asyncio

    paragraphs_text = "\n\n".join(
        f"[段落 {j+1}] {blk.text[:300]}" for j, blk in enumerate(batch)
    )
    system_msg = "你是 GNC 航天设计报告的结构化分析专家。你只返回严格的 JSON 数组，不要解释、不要 markdown。"
    user_msg = (
        f"下面是一批相邻的文档段落（共 {len(batch)} 段）。\n"
        "请判断哪些相邻段落在主题上属于同一个逻辑章节，并为每个逻辑章节建议一个简洁的工程标题。\n\n"
        '输出格式（严格 JSON 数组）:\n'
        '[{"title": "章节标题", "start": 1, "end": 3}, ...]\n'
        f"start/end 是段落编号（从 1 开始）。段落必须连续且不重叠，覆盖所有 {len(batch)} 段。\n\n"
        f"=== 文档段落 ===\n{paragraphs_text}\n"
    )

    max_retries = model_config.get("retries", 3)
    delay_base = model_config.get("delay_between_retries", 2)
    exp_backoff = model_config.get("exponential_backoff", True)

    async def _do_stream_call() -> str:
        """直接用 openai SDK 流式调用，收集完整响应文本。"""
        import openai as _openai

        logger.info(f"[LLM Chunking] 批次 {batch_no + 1}/{total_batches} 开始 (已获取槽位, 流式请求中...)")

        client = _openai.OpenAI(
            api_key=model_config["api_key"],
            base_url=model_config["base_url"],
            timeout=model_config.get("timeout", 180),
        )

        create_kwargs: dict = {
            "model":       model_config["model_id"],
            "temperature": model_config.get("temperature", 0),
            "max_tokens":  model_config.get("max_tokens", 600),
            "stream":      True,
            "messages": [
                {"role": "system", "content": system_msg},
                {"role": "user",   "content": user_msg},
            ],
        }
        if model_config.get("response_format"):
            create_kwargs["response_format"] = model_config["response_format"]
        if model_config.get("extra_body"):
            create_kwargs["extra_body"] = model_config["extra_body"]

        def _sync_stream_collect() -> str:
            chunks: list[str] = []
            with client.chat.completions.create(**create_kwargs) as stream:
                for event in stream:
                    delta = event.choices[0].delta if event.choices else None
                    if delta and delta.content:
                        chunks.append(delta.content)
            return "".join(chunks)

        loop = _asyncio.get_event_loop()
        return await loop.run_in_executor(None, _sync_stream_collect)

    try:
        logger.debug(f"[LLM Chunking] 批次 {batch_no + 1}/{total_batches} 排队等待并发槽位...")

        content = ""
        last_exc: Exception | None = None
        for attempt in range(max_retries + 1):
            try:
                if semaphore is not None:
                    async with semaphore:
                        content = await _do_stream_call()
                else:
                    content = await _do_stream_call()
                break
            except Exception as e:
                last_exc = e
                err_str = str(e).lower()
                retryable = any(kw in err_str for kw in ("timeout", "timed out", "connection", "502", "503", "504"))
                if attempt < max_retries and retryable:
                    wait_s = delay_base * (2 ** attempt) if exp_backoff else delay_base
                    logger.warning(
                        f"[LLM Chunking] 批次 {batch_no + 1}/{total_batches} 第 {attempt + 1} 次失败 "
                        f"({type(e).__name__}), {wait_s}s 后重试..."
                    )
                    await _asyncio.sleep(wait_s)
                else:
                    raise

        if not content and last_exc:
            raise last_exc

        arr_match = re.search(r'\[.*\]', content, re.DOTALL)
        if not arr_match:
            raise ValueError(f"未匹配到 JSON 数组, 内容: {content[:200]}")
        spans_raw = _json.loads(arr_match.group())
        result: list[dict] = []
        for span in spans_raw:
            start_local = max(0, min(int(span.get("start", 1)) - 1, len(batch) - 1))
            end_local = max(start_local, min(int(span.get("end", len(batch))) - 1, len(batch) - 1))
            title = (span.get("title") or "").strip()
            if title:
                result.append({
                    "start_idx": global_offset + start_local,
                    "end_idx": global_offset + end_local,
                    "title": title,
                })
        logger.info(f"[LLM Chunking] 批次 {batch_no + 1}/{total_batches} 完成: 提取 {len(result)} 个结构节")
        return result
    except Exception as e:
        logger.warning(f"[LLM Chunking] 批次 {batch_no + 1}/{total_batches} 最终失败 (已耗尽重试): {e}")
        return [{
            "start_idx": global_offset,
            "end_idx": global_offset + len(batch) - 1,
            "title": batch[0].text[:40].strip() or f"段落组 {batch_no + 1}",
        }] if batch else []


async def llm_semantic_chunking(
    parsed_doc: ParsedDocument,
    model_id: str = "",
    window_size: int = 0,   # 0 = 从环境变量读取
    overlap: int = 0,       # 0 = 从环境变量读取
    toc_entries: list[DocumentTocEntry] | None = None,
    toc_block_indexes: set[int] | None = None,
) -> DocumentSectionTree:
    """
    基于大模型的语义切分管道（异步并发版本）。

    策略:
      1. 用代码将文档粗切成 ~400 字/段的细粒度段落 (fine_paragraphs)
      2. 滑动窗口 (window_size=10, overlap=2) 将相邻段落组成批次
      3. asyncio.gather 并发请求 LLM 判断语义边界 + 建议章节标题
      4. 合并各批次结果，反映射回 DocumentSection 列表，构建 SectionTree

    模型选择优先级:
      - 若传入 model_id 则使用指定模型
      - 否则使用 get_lightweight_model() （LIGHT_LLM_* / LIGHTWEIGHT_* 环境变量）
      - 如果轻量化模型未配置，和回退到主模型

    若 LLM 调用全部失败/超时，回退到代码规则切分 (build_section_tree)。
    """
    import asyncio as _asyncio

    try:
        import openai as _openai  # noqa: F401 — 仅做可用性检查
    except ImportError:
        logger.warning("[LLM Chunking] openai SDK 未安装，回退代码规则切分")
        return build_section_tree(parsed_doc, toc_entries=toc_entries, toc_block_indexes=toc_block_indexes)

    prepared_doc, toc_entries, toc_block_indexes = _prepare_doc_for_chunking(
        parsed_doc,
        toc_entries=toc_entries,
        toc_block_indexes=toc_block_indexes,
    )
    fine_paragraphs = _fine_split_to_paragraphs(prepared_doc)
    if not fine_paragraphs:
        logger.info("[LLM Chunking] 文档无内容，回退代码规则切分")
        return build_section_tree(prepared_doc, toc_entries=toc_entries, toc_block_indexes=set())

    # 从环境变量读取窗口参数（调用方传入非零则优先使用传入值）
    _default_window = int(os.environ.get("CHUNKING_WINDOW_SIZE", "5"))
    _default_overlap = int(os.environ.get("CHUNKING_OVERLAP", "1"))
    effective_window = window_size if window_size > 0 else _default_window
    effective_overlap = overlap if overlap > 0 else _default_overlap
    effective_overlap = min(effective_overlap, effective_window - 1)  # overlap 不得 >= window

    # 构建批次列表
    batches: list[list[ParsedDocumentBlock]] = []
    n = len(fine_paragraphs)
    step = max(1, effective_window - effective_overlap)
    i = 0
    while i < n:
        batches.append(fine_paragraphs[i: i + effective_window])
        i += step

    logger.info(
        f"[LLM Chunking] 细粒度段落: {n} 个, 批次: {len(batches)} 个 "
        f"(window={effective_window}, overlap={effective_overlap}, step={step}, 并发执行)"
    )

    # ── 切片专用配置（LIGHT_LLM_* → LLM_*，兼容 LIGHTWEIGHT_* / PARSING_LLM_* / OPENAI_*）──
    from data_agent.core.llm_profiles import get_llm_profile

    parsing_profile = get_llm_profile("parsing")
    lw_model_name = model_id or parsing_profile.model
    lw_api_key = parsing_profile.api_key
    lw_base_url = parsing_profile.base_url

    if not lw_model_name or not lw_api_key or not lw_base_url:
        logger.warning("[LLM Chunking] 解析 LLM 未完整配置（LIGHT_LLM_* / LLM_*），回退代码规则切分")
        return build_section_tree(prepared_doc, toc_entries=toc_entries, toc_block_indexes=set())

    model_config: dict = {
        "model_id":              lw_model_name,
        "api_key":               lw_api_key,
        "base_url":              lw_base_url,
        "temperature":           0,
        "timeout":               180,
        "max_tokens":            600,
        "retries":               3,
        "delay_between_retries": 2,
        "exponential_backoff":   True,
        "response_format":       None,
        "extra_body":            parsing_profile.extra_body,
    }
    logger.info(
        f"[LLM Chunking] 切片配置: {lw_model_name} @ {lw_base_url} "
        f"(stream=True, max_tokens=600, retries=3, timeout=180, json_mode=True)"
    )

    # 生成每个批次的全局偏移起始位置
    global_offsets = []
    offset = 0
    for _ in batches:
        global_offsets.append(offset)
        offset += step

    # 从env读取最大并发数，默认 3（对免费账号压力友好）
    max_concurrency = int(os.environ.get("CHUNKING_MAX_CONCURRENCY", "3"))
    semaphore = _asyncio.Semaphore(max_concurrency)
    logger.info(f"[LLM Chunking] 并发限制: {max_concurrency} (同时进行的最大批次数)")

    # asyncio.gather 并发运行所有批次
    total_batches = len(batches)
    tasks = [
        _run_batch_async(batch_no, batch, global_offsets[batch_no], step, model_config, total_batches, semaphore)
        for batch_no, batch in enumerate(batches)
    ]

    batch_results = await _asyncio.gather(*tasks)

    # 合并所有批次的 section_spans
    section_spans: list[dict] = []
    for spans in batch_results:
        section_spans.extend(spans)

    if not section_spans:
        logger.warning("[LLM Chunking] 未能提取任何语义段，回退代码规则切分")
        return build_section_tree(prepared_doc, toc_entries=toc_entries, toc_block_indexes=set())

    # 合并并去重（相邻重叠段落只保留一次）
    section_spans.sort(key=lambda x: x["start_idx"])
    merged: list[dict] = []
    for span in section_spans:
        if merged and span["start_idx"] <= merged[-1]["end_idx"]:
            merged[-1]["end_idx"] = max(merged[-1]["end_idx"], span["end_idx"])
        else:
            merged.append(dict(span))

    # 确保覆盖全部 fine_paragraphs
    if merged and merged[-1]["end_idx"] < len(fine_paragraphs) - 1:
        merged[-1]["end_idx"] = len(fine_paragraphs) - 1

    # 构建 DocumentSectionTree
    sections: list[DocumentSection] = []
    for idx, span in enumerate(merged):
        start_idx = span["start_idx"]
        end_idx = span["end_idx"]
        para_texts = [
            fine_paragraphs[j].text
            for j in range(start_idx, min(end_idx + 1, len(fine_paragraphs)))
        ]
        section = DocumentSection(
            section_id=str(uuid.uuid4())[:12],
            title=span["title"],
            level=1,
            number=str(idx + 1),
            start_block_index=start_idx,
            end_block_index=end_idx,
            text="\n\n".join(para_texts),
            source_file_name=prepared_doc.file_name,
        )
        sections.append(section)

    root_ids = [s.section_id for s in sections]
    tree = DocumentSectionTree(
        sections=sections,
        root_section_ids=root_ids,
        toc_entries=_attach_toc_matches(toc_entries, sections),
    )
    logger.info(f"[LLM Chunking] 完成: {len(sections)} 个语义章节 (共 {len(batches)} 个批次并发运行)")
    return tree
