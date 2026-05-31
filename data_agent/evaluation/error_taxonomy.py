from __future__ import annotations


ERROR_CATEGORIES = {
    "parse_error",
    "unsupported_format",
    "llm_failure",
    "knowledge_missing",
    "schema_invalid",
    "timeout",
    "unknown",
}


def classify_error(message: str) -> str:
    text = (message or "").lower()
    if any(token in text for token in ("unsupported", "不支持", "extension", "尚未执行", "low_confidence_visual")):
        return "unsupported_format"
    if any(token in text for token in ("parse", "解析", "pdftotext")):
        return "parse_error"
    if any(token in text for token in ("llm", "agno", "openai", "model")):
        return "llm_failure"
    if any(token in text for token in ("knowledge", "not found or empty", "标准", "知识")):
        return "knowledge_missing"
    if any(token in text for token in ("schema", "validation", "pydantic")):
        return "schema_invalid"
    if "timeout" in text or "timed out" in text:
        return "timeout"
    return "unknown"
