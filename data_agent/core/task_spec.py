"""TaskSpec: serializable DAG node for SMART committee Router/Decompose."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

KIND_SMART_SPECIALIST_REVIEW = "smart_specialist_review"
KIND_FORMAT_GATE = "format_gate"
KIND_ARBITER_SUMMARY = "arbiter_summary"


def stable_task_id(kind: str, specialist_id: str) -> str:
    """Deterministic task id from kind and specialist."""
    if kind == KIND_SMART_SPECIALIST_REVIEW:
        return f"smart_specialist:{specialist_id}"
    return f"{kind}:{specialist_id}"


@dataclass
class TaskSpec:
    task_id: str
    kind: str
    agent_id: str
    specialist_id: str
    title: str
    depends_on: list[str] = field(default_factory=list)
    input_summary: dict[str, Any] = field(default_factory=dict)
    required_evidence: bool = True
    profile: dict[str, Any] | None = None
    priority: int | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "task_id": self.task_id,
            "kind": self.kind,
            "agent_id": self.agent_id,
            "specialist_id": self.specialist_id,
            "title": self.title,
            "depends_on": list(self.depends_on),
            "input_summary": dict(self.input_summary),
            "required_evidence": self.required_evidence,
        }
        if self.profile is not None:
            payload["profile"] = dict(self.profile)
        if self.priority is not None:
            payload["priority"] = self.priority
        return payload


def task_spec_to_dict(spec: TaskSpec) -> dict[str, Any]:
    return spec.to_dict()


def task_spec_from_dict(payload: dict[str, Any]) -> TaskSpec:
    profile = payload.get("profile")
    priority = payload.get("priority")
    return TaskSpec(
        task_id=str(payload.get("task_id") or ""),
        kind=str(payload.get("kind") or KIND_SMART_SPECIALIST_REVIEW),
        agent_id=str(payload.get("agent_id") or payload.get("specialist_id") or ""),
        specialist_id=str(payload.get("specialist_id") or payload.get("agent_id") or ""),
        title=str(payload.get("title") or ""),
        depends_on=[str(item) for item in payload.get("depends_on") or []],
        input_summary=dict(payload.get("input_summary") or {}),
        required_evidence=bool(payload.get("required_evidence", True)),
        profile=dict(profile) if isinstance(profile, dict) else None,
        priority=int(priority) if priority is not None else None,
    )


def task_specs_to_dicts(specs: list[TaskSpec]) -> list[dict[str, Any]]:
    return [spec.to_dict() for spec in specs]


def task_specs_from_dicts(payload: list[Any] | None) -> list[TaskSpec]:
    if not payload:
        return []
    return [
        task_spec_from_dict(item)
        for item in payload
        if isinstance(item, dict)
    ]


__all__ = [
    "KIND_ARBITER_SUMMARY",
    "KIND_FORMAT_GATE",
    "KIND_SMART_SPECIALIST_REVIEW",
    "TaskSpec",
    "stable_task_id",
    "task_spec_from_dict",
    "task_spec_to_dict",
    "task_specs_from_dicts",
    "task_specs_to_dicts",
]
