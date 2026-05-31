from __future__ import annotations

from pydantic import BaseModel, Field


class DocumentInput(BaseModel):
    file_name: str
    content_type: str = "base64"  # url | base64 | path
    content: str
    role_hint: str | None = None


class TaskSubmitRequest(BaseModel):
    task_description: str
    processing_mode: str = "OPTIMAL"
    output_format: str = "json"
    output_schema: str | None = None
    package_id: str | None = None
    documents: list[DocumentInput] = Field(default_factory=list)
    use_dag: bool = Field(
        default=False,
        description=(
            "Run material_parse/data_structuring via shared DAG pipeline. "
            "Ignored for product_assurance_reliability_safety (PACKAGE_REVIEW) and "
            "cross_package_compare, which require legacy Review-Plus workflows."
        ),
    )


class TaskSubmitResponse(BaseModel):
    task_id: str
    status: str = "pending"
    created_at: str


class TaskStatusResponse(BaseModel):
    task_id: str
    status: str
    progress: float
    current_step: str
    scenario: str
    parser_trace: list[dict] = Field(default_factory=list)
    error: str | None = None
    created_at: str = ""
    started_at: str | None = None
    completed_at: str | None = None
