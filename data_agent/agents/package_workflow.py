"""Phase 1 文档包审查 Workflow — 委托完整 Review-Plus 十步链路。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from data_agent.domain.material_roles import TaskScenario
from data_agent.review.schemas import PackageReviewReport, ParsedMaterial
from data_agent.review_plus.integration import map_review_plus_to_task_fields, run_review_plus_package


@dataclass
class PackageWorkflowContext:
    scenario: TaskScenario
    package_id: str | None = None
    materials: list[ParsedMaterial] = field(default_factory=list)
    evidence_pools: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    section_trees: dict[str, dict] = field(default_factory=dict)
    parser_trace: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    on_step: Callable[[str, float], None] | None = None

    def step(self, name: str, progress: float) -> None:
        if self.on_step:
            self.on_step(name, progress)


class PackageReviewWorkflow:
    """兼容层：内部调用 aq-aero 同源 Review-Plus 十步 workflow。"""

    def run(self, ctx: PackageWorkflowContext) -> PackageReviewReport:
        uploads = []
        for material in ctx.materials:
            path = material.file_path
            if not path:
                continue
            from pathlib import Path

            file_path = Path(path)
            if file_path.exists():
                uploads.append((material.name, file_path.read_bytes()))
        if not uploads:
            raise ValueError("Review-Plus workflow requires material file paths")

        rp_task = run_review_plus_package(
            name=ctx.package_id or "package_review",
            uploads=uploads,
            parser_type="local",
            on_step=ctx.on_step,
        )
        mapped = map_review_plus_to_task_fields(rp_task)
        report = rp_task.report
        if not report:
            raise RuntimeError("Review-Plus report missing")

        from data_agent.review.schemas import CrossDocFinding, PackageReviewReport

        return PackageReviewReport(
            scenario=ctx.scenario.value,
            package_id=ctx.package_id,
            check_items=list(rp_task.check_items),
            total_check_items=report.total_check_items,
            satisfied_count=report.satisfied_count,
            not_satisfied_count=report.not_satisfied_count,
            insufficient_evidence_count=report.insufficient_evidence_count,
            critical_count=report.critical_count,
            findings=list(rp_task.findings),
            cross_doc_findings=[
                CrossDocFinding(
                    title=item.get("title", ""),
                    description=item.get("description", ""),
                    severity=item.get("severity", "major"),
                    finding_type=item.get("item_type", "cross_document_issue"),
                    source_quotes=[item.get("source_quote", "")] if item.get("source_quote") else [],
                )
                for item in mapped["cross_doc_findings"]
            ],
            conclusion=mapped["review_conclusion"],
            summary=report.summary,
            markdown=mapped["review_report_markdown"],
        )
