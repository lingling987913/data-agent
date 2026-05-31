from __future__ import annotations

import re


def _normalize_text(text: str) -> str:
    stripped = text or ""
    stripped = re.sub(r"\|", " ", stripped)
    stripped = re.sub(r"-{3,}", " ", stripped)
    stripped = re.sub(r"[。，、；：]", " ", stripped)
    collapsed = re.sub(r"\s+", " ", stripped.strip())
    return collapsed


def _levenshtein_chars(left: str, right: str) -> int:
    if left == right:
        return 0
    if not left:
        return len(right)
    if not right:
        return len(left)
    previous = list(range(len(right) + 1))
    for i, left_char in enumerate(left, start=1):
        current = [i]
        for j, right_char in enumerate(right, start=1):
            insert_cost = current[j - 1] + 1
            delete_cost = previous[j] + 1
            replace_cost = previous[j - 1] + (0 if left_char == right_char else 1)
            current.append(min(insert_cost, delete_cost, replace_cost))
        previous = current
    return previous[-1]


def _levenshtein_tokens(left: list[str], right: list[str]) -> int:
    if left == right:
        return 0
    if not left:
        return len(right)
    if not right:
        return len(left)
    previous = list(range(len(right) + 1))
    for i, left_token in enumerate(left, start=1):
        current = [i]
        for j, right_token in enumerate(right, start=1):
            insert_cost = current[j - 1] + 1
            delete_cost = previous[j] + 1
            replace_cost = previous[j - 1] + (0 if left_token == right_token else 1)
            current.append(min(insert_cost, delete_cost, replace_cost))
        previous = current
    return previous[-1]


def extract_document_text(result: dict) -> str:
    """Collect parsed text from golden/preview structure results."""
    parts: list[str] = []
    for chunk in result.get("chunks") or []:
        if not isinstance(chunk, dict):
            continue
        text = str(chunk.get("chunk_text") or chunk.get("text") or "").strip()
        if text:
            parts.append(text)
    if parts:
        return "\n".join(parts)

    document_ir = result.get("document_ir") or {}
    for block in document_ir.get("layout_blocks") or []:
        if not isinstance(block, dict):
            continue
        text = str(block.get("text") or "").strip()
        if text:
            parts.append(text)
    return "\n".join(parts)


def ocr_cer_wer_score(*, reference: str, hypothesis: str) -> dict[str, float | int | None]:
    """Character/word error rates against golden OCR reference text."""
    ref = _normalize_text(reference)
    hyp = _normalize_text(hypothesis)
    if not ref:
        return {
            "cer": None,
            "wer": None,
            "reference_length": 0,
            "hypothesis_length": len(hyp),
        }

    char_distance = _levenshtein_chars(ref, hyp)
    ref_tokens = ref.split()
    hyp_tokens = hyp.split()
    word_distance = _levenshtein_tokens(ref_tokens, hyp_tokens)
    cer = char_distance / len(ref)
    wer = word_distance / len(ref_tokens) if ref_tokens else 0.0
    return {
        "cer": round(cer, 4),
        "wer": round(wer, 4),
        "reference_length": len(ref),
        "hypothesis_length": len(hyp),
    }


def ocr_cer_scalar(metrics: dict[str, float | int | None]) -> float | None:
    cer = metrics.get("cer")
    return float(cer) if cer is not None else None


def ocr_wer_scalar(metrics: dict[str, float | int | None]) -> float | None:
    wer = metrics.get("wer")
    return float(wer) if wer is not None else None
