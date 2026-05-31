"""Schema validation and repair helpers with structured failure logging."""

from __future__ import annotations

import json
import logging
from typing import Any, Callable, TypeVar

from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)
PayloadNormalizer = Callable[[Any, type[T]], Any]


class SchemaValidationError(ValueError):
    """Raised when structured output cannot be validated or repaired."""

    def __init__(self, schema_name: str, payload: Any, errors: list[str]):
        self.schema_name = schema_name
        self.payload = payload
        self.errors = errors
        super().__init__(f"{schema_name} validation failed: {'; '.join(errors)}")


def _strip_markdown_fence(text: str) -> str:
    lines = [line for line in text.splitlines() if not line.strip().startswith("```")]
    return "\n".join(lines).strip()


def _coerce_payload(payload: Any, schema: type[BaseModel] | None = None) -> Any:
    if isinstance(payload, BaseModel):
        return payload.model_dump()
    if isinstance(payload, str):
        text = _strip_markdown_fence(payload.strip())
        if not text:
            raise ValueError("empty string payload")
        payload = json.loads(text)
    if isinstance(payload, list) and schema is not None:
        field_names = list(schema.model_fields.keys())
        if len(field_names) == 1:
            return {field_names[0]: payload}
    return payload


def validate_structured_output(
    payload: Any,
    schema: type[T],
    *,
    attempt_repair: bool = True,
    payload_normalizer: PayloadNormalizer[T] | None = None,
) -> T:
    """Validate Agno response content against a Pydantic schema.

    Logs every validation failure. When ``attempt_repair`` is True, tries to
    parse markdown-fenced JSON strings before giving up.
    """
    schema_name = getattr(schema, "__name__", str(schema))

    if isinstance(payload, schema):
        return payload

    try:
        normalized = payload_normalizer(payload, schema) if payload_normalizer else payload
        coerced = _coerce_payload(normalized, schema)
        return schema.model_validate(coerced)
    except (ValidationError, json.JSONDecodeError, ValueError, TypeError) as first_exc:
        first_errors = [str(first_exc)]
        logger.warning(
            "schema_validation_failed schema=%s attempt=primary error=%s payload_type=%s",
            schema_name,
            first_exc,
            type(payload).__name__,
        )

    if not attempt_repair or not isinstance(payload, str):
        raise SchemaValidationError(schema_name, payload, first_errors)

    try:
        repaired = _coerce_payload(payload, schema)
        result = schema.model_validate(repaired)
        logger.info("schema_validation_repaired schema=%s", schema_name)
        return result
    except (ValidationError, json.JSONDecodeError, ValueError, TypeError) as repair_exc:
        repair_errors = [str(repair_exc)]
        logger.error(
            "schema_validation_failed schema=%s attempt=repair error=%s",
            schema_name,
            repair_exc,
        )
        raise SchemaValidationError(schema_name, payload, first_errors + repair_errors) from repair_exc


def response_content(response: Any) -> Any:
    """Return Agno response content while tolerating tests that pass raw payloads."""
    return getattr(response, "content", response)


def _schema_guided_repair_prompt(prompt: str, payload: Any, schema: type[BaseModel], error: Exception) -> str:
    schema_name = getattr(schema, "__name__", str(schema))
    return (
        "上一次输出未通过结构化 schema 校验。请只返回一个 JSON 对象，不要 Markdown，不要解释。\n"
        f"schema_name={schema_name}\n"
        f"json_schema={json.dumps(schema.model_json_schema(), ensure_ascii=False)}\n"
        f"validation_error={str(error)}\n"
        f"previous_payload={json.dumps(payload, ensure_ascii=False, default=str)[:6000]}\n"
        f"original_task={prompt[:6000]}"
    )


def run_agent_with_validation(
    agent: Any,
    prompt: str,
    schema: type[T],
    *,
    payload_normalizer: PayloadNormalizer[T] | None = None,
    retry_once: bool = True,
) -> T:
    """Run an Agno agent and validate the structured output, with one schema-guided retry."""
    response = agent.run(prompt)
    payload = response_content(response)
    try:
        return validate_structured_output(payload, schema, payload_normalizer=payload_normalizer)
    except SchemaValidationError as first_exc:
        if not retry_once:
            raise
        logger.warning(
            "schema_validation_retry schema=%s error=%s",
            getattr(schema, "__name__", str(schema)),
            first_exc,
        )
        repair_prompt = _schema_guided_repair_prompt(prompt, payload, schema, first_exc)
        repair_response = agent.run(repair_prompt)
        return validate_structured_output(
            response_content(repair_response),
            schema,
            attempt_repair=False,
            payload_normalizer=payload_normalizer,
        )
