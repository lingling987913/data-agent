from __future__ import annotations

import base64
import shutil
from pathlib import Path
from typing import Any

from data_agent.agents.package_workflow import PackageReviewWorkflow, PackageWorkflowContext
from data_agent.review_plus.integration import map_review_plus_to_task_fields, run_review_plus_package
from data_agent.core.config import UPLOAD_DIR, ensure_dirs
from data_agent.domain.material_roles import (
    MaterialRole,
    MaterialSummary,
    ReviewCheckItem,
    StructuredTaskResult,
    TaskScenario,
    detect_scenario,
)
from data_agent.domain.review_rule_schema import extract_review_check_items
from data_agent.domain.tdms_extractor import extract_tdms_metadata
from data_agent.parsing.schemas import ParsedDocument
from data_agent.evaluation.execution_metrics import build_execution_metrics_snapshot
from data_agent.evaluation.parser_trace_summary import build_parser_trace_summary
from data_agent.parsing.parse_artifacts import (
    StructureArtifact,
    build_parse_only_artifact_from_parsed,
    merge_parse_and_structure,
    parse_materials_to_batch,
    per_file_structure_slices,
)
from data_agent.services.task_classifier import classify_batch, to_material_role
from data_agent.services.pipeline_runner import (
    map_dag_trace_to_task_result,
    run_dag_pipeline_sync,
    should_use_dag_for_scenario,
)
from data_agent.review.cross_package_service import compare_document_packages
from data_agent.review.schemas import ParsedMaterial, ReviewPlusMaterialRole
from data_agent.agents.format_guard.mode_policy import resolve_parser_type


def _save_document(doc: dict[str, Any], task_id: str) -> tuple[str, str]:
    ensure_dirs()
    file_name = doc["file_name"]
    if file_name.startswith("~$"):
        raise ValueError(f"Skip temp file: {file_name}")

    task_dir = UPLOAD_DIR / task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    dest = task_dir / file_name

    content_type = doc.get("content_type", "base64")
    if content_type == "url":
        import requests

        response = requests.get(doc["content"], timeout=120)
        response.raise_for_status()
        dest.write_bytes(response.content)
    elif content_type == "base64":
        dest.write_bytes(base64.b64decode(doc["content"]))
    elif content_type == "path":
        src = Path(doc["content"])
        if not src.exists():
            raise FileNotFoundError(f"Local path not found: {src}")
        shutil.copy2(src, dest)
    else:
        raise ValueError(f"Unsupported content_type: {content_type}")

    return str(dest), file_name


def _parser_type_for_file(file_name: str, processing_mode: str) -> str:
    return resolve_parser_type(file_name, processing_mode)


def _parser_type_for_task_material(file_name: str, processing_mode: str) -> str:
    lowered = file_name.lower()
    if lowered.endswith((".xlsx", ".xls")):
        return "local"
    return _parser_type_for_file(file_name, processing_mode)


def _parser_trace_from_parsed_item(item: dict[str, Any]) -> list[dict[str, Any]]:
    traces: list[dict[str, Any]] = [
        {
            "parser": item.get("parser_name") or "",
            "status": item.get("parse_status") or "failed",
        }
    ]
    for fallback in item.get("parser_fallback_logs") or []:
        traces.append({**fallback, "kind": "parser_fallback"})
    for healing in item.get("self_healing_records") or []:
        traces.append({**healing, "kind": "self_healing"})
    return traces


def _role_to_enum(role) -> ReviewPlusMaterialRole:
    mapping = {
        "review_rule": ReviewPlusMaterialRole.REVIEW_RULE,
        "checklist": ReviewPlusMaterialRole.CHECKLIST,
        "task_book": ReviewPlusMaterialRole.TASK_BOOK,
        "subject_report": ReviewPlusMaterialRole.SUBJECT_REPORT,
        "acceptance_report": ReviewPlusMaterialRole.SUBJECT_REPORT,
        "motor_spec": ReviewPlusMaterialRole.SUBJECT_DOCUMENT,
        "engineering_drawing": ReviewPlusMaterialRole.SUPPORTING_ATTACHMENT,
        "test_data": ReviewPlusMaterialRole.SUPPORTING_ATTACHMENT,
    }
    value = role.value if hasattr(role, "value") else str(role)
    return mapping.get(value, ReviewPlusMaterialRole.UNKNOWN)


def _package_label(material: ParsedMaterial) -> str:
    text = f"{material.name} {material.content[:400]}"
    if "月兔" in text:
        return "q1"
    if "蓬莱" in text:
        return "q2"
    return ""


def _split_packages(
    materials: list[ParsedMaterial],
    evidence_pools: dict[str, list],
) -> tuple[list[ParsedMaterial], dict, list[ParsedMaterial], dict]:
    q1_m: list[ParsedMaterial] = []
    q1_p: dict = {}
    q2_m: list[ParsedMaterial] = []
    q2_p: dict = {}

    labels = [_package_label(m) for m in materials]
    has_q1 = any(label == "q1" for label in labels)
    has_q2 = any(label == "q2" for label in labels)
    has_unassigned = any(not label for label in labels)

    if has_q1 and has_q2 and has_unassigned and len(materials) >= 6:
        split_at = len(materials) // 2
        q1_m, q2_m = materials[:split_at], materials[split_at:]
    else:
        unassigned: list[ParsedMaterial] = []
        for m, label in zip(materials, labels):
            if label == "q1":
                q1_m.append(m)
            elif label == "q2":
                q2_m.append(m)
            else:
                unassigned.append(m)

        if unassigned:
            if not q1_m and not q2_m:
                split_at = len(materials) // 2
                q1_m, q2_m = materials[:split_at], materials[split_at:]
            elif q1_m:
                q1_m.extend(unassigned)
            else:
                q2_m.extend(unassigned)

    for m in q1_m:
        if m.name in evidence_pools:
            q1_p[m.name] = evidence_pools[m.name]
    for m in q2_m:
        if m.name in evidence_pools:
            q2_p[m.name] = evidence_pools[m.name]
    return q1_m, q1_p, q2_m, q2_p


def run_document_task(task) -> dict[str, Any]:
    """Execute a document parsing / package review task."""
    ensure_dirs()
    task.current_step = "ingest_documents"
    task.progress = 0.1

    materials: list[MaterialSummary] = []
    parsed_materials: list[ParsedMaterial] = []
    section_trees: dict[str, dict] = {}
    evidence_pools: dict[str, list] = {}
    check_items: list[ReviewCheckItem] = []
    warnings: list[str] = []
    parser_trace: list[dict[str, Any]] = []
    markdown_parts: list[str] = []
    tdms_metadata: dict | None = None
    extracted_parameters: list[dict] = []
    extracted_objects: list[dict] = []
    trace_link_candidates: list[dict] = []
    traceability_summaries: dict[str, dict] = {}
    document_irs: dict[str, dict] = {}
    parse_material_inputs: list[dict[str, Any]] = []
    saved_docs: list[tuple[dict[str, Any], str, str, MaterialRole]] = []

    def on_step(name: str, progress: float) -> None:
        task.current_step = name
        task.progress = max(task.progress, progress)

    total = max(len(task.documents), 1)
    pending_docs: list[tuple[dict[str, Any], str, str]] = []
    for idx, doc in enumerate(task.documents):
        task.current_step = f"parse:{doc.get('file_name', '')}"
        task.progress = 0.1 + 0.5 * (idx / total)
        file_path, file_name = _save_document(doc, task.task_id)
        pending_docs.append((doc, file_path, file_name))

    classification = classify_batch(
        [
            {
                "file_name": file_name,
                "file_path": file_path,
                "role_hint": doc.get("role_hint"),
                "content": doc.get("content_preview") or doc.get("preview_content") or "",
            }
            for doc, file_path, file_name in pending_docs
        ],
        objective=task.task_description or "",
    )
    role_by_name = {item.file_name: item for item in classification.material_roles}
    if classification.metadata.scenario:
        scenario = TaskScenario(classification.metadata.scenario)
    else:
        scenario = detect_scenario(task.documents)
    task.scenario = scenario.value

    use_dag_requested = getattr(task, "use_dag", False)
    dag_capable = should_use_dag_for_scenario(scenario)
    if use_dag_requested and not dag_capable:
        warnings.append(
            f"use_dag=true ignored for scenario {scenario.value}: "
            "legacy Review-Plus workflow required"
        )
    if dag_capable:
        task.current_step = "dag_pipeline"
        task.progress = 0.2
        materials_meta = [
            {
                "file_name": file_name,
                "file_path": file_path,
                "role_hint": doc.get("role_hint") or "",
                "processing_mode": task.processing_mode,
            }
            for doc, file_path, file_name in pending_docs
        ]
        metadata = {
            "materials": materials_meta,
            "processing_mode": task.processing_mode,
            "task_classification": classification.model_dump(mode="json"),
            "task_route": classification.route,
        }
        trace = run_dag_pipeline_sync(
            task.task_description or "文档解析与结构化",
            plan_id=task.task_id,
            metadata=metadata,
        )
        task.current_step = "finalize"
        task.progress = 0.98
        result = map_dag_trace_to_task_result(
            trace,
            task_id=task.task_id,
            scenario=scenario,
            classification=classification,
            package_id=task.package_id,
        )
        task.parser_trace = result.get("parser_trace") or []
        return result

    for doc, file_path, file_name in pending_docs:
        role_hint = doc.get("role_hint")
        classified_item = role_by_name.get(file_name)
        role_value = classified_item.role if classified_item else ""
        role = to_material_role(role_value or role_hint or "", file_name)

        if file_name.lower().endswith(".tdms"):
            tdms_metadata = extract_tdms_metadata(file_path)
            parsed_content = f"[TDMS] {tdms_metadata.get('file_name')} size={tdms_metadata.get('file_size_bytes')}"
            materials.append(
                MaterialSummary(
                    file_name=file_name,
                    role=role,
                    parser_name=tdms_metadata.get("parser_name", "tdms"),
                    parse_status=tdms_metadata.get("parse_status", "ok"),
                    block_count=tdms_metadata.get("channel_count", 0) or 0,
                )
            )
            parsed_materials.append(
                ParsedMaterial(
                    name=file_name,
                    file_path=file_path,
                    content=parsed_content,
                    parser_name=str(tdms_metadata.get("parser_name", "tdms")),
                    parse_status=str(tdms_metadata.get("parse_status", "ok")),
                    role=_role_to_enum(role),
                )
            )
            continue

        saved_docs.append((doc, file_path, file_name, role))
        parse_material_inputs.append(
            {
                "file_path": file_path,
                "file_name": file_name,
                "parser_type": _parser_type_for_task_material(file_name, task.processing_mode),
                "processing_mode": task.processing_mode,
            }
        )

    if parse_material_inputs:
        parsed = parse_materials_to_batch(
            parse_material_inputs,
            default_processing_mode=task.processing_mode,
        )
        parse_only = build_parse_only_artifact_from_parsed(parsed)
        parse_only.artifact_id = f"task-{task.task_id}"
        artifact = merge_parse_and_structure(
            parse_only,
            StructureArtifact(parse_artifact_id=parse_only.artifact_id),
        )
        extracted_parameters = list(artifact.extracted_parameters)
        extracted_objects = list(artifact.extracted_objects)
        trace_link_candidates = list(artifact.trace_link_candidates)
        warnings = list(artifact.warnings)

        for item in parsed.get("documents") or []:
            file_name = str(item.get("file_name") or "")
            _, file_path, _, role = next(
                (entry for entry in saved_docs if entry[2] == file_name),
                ({}, "", file_name, to_material_role("", file_name)),
            )
            parser_trace.extend(_parser_trace_from_parsed_item(item))
            document_payload = item.get("document")
            block_count = int(item.get("block_count") or 0)
            section_count = 0
            if document_payload and artifact is not None:
                slices = per_file_structure_slices(artifact, file_name)
                section_trees[file_name] = slices["section_tree"]
                evidence_pools[file_name] = list(slices["evidence_pool"].get("evidences") or [])
                document_irs[file_name] = slices["document_ir"]
                traceability_summaries[file_name] = artifact.traceability_matrix_summary
                section_count = int(slices.get("section_count") or 0)
                markdown_parts.append(f"# {file_name}\n\n{(item.get('content') or '')[:8000]}")
            materials.append(
                MaterialSummary(
                    file_name=file_name,
                    role=role,
                    parser_name=str(item.get("parser_name") or ""),
                    parse_status=str(item.get("parse_status") or "failed"),
                    block_count=block_count,
                    section_count=section_count,
                )
            )
            parsed_materials.append(
                ParsedMaterial(
                    name=file_name,
                    file_path=file_path,
                    file_type=str(item.get("file_type") or Path(file_name).suffix.lower().lstrip(".")),
                    content=str(item.get("content") or ""),
                    parser_name=str(item.get("parser_name") or ""),
                    parse_status=str(item.get("parse_status") or "failed"),
                    warnings=list(item.get("warnings") or []),
                    role=_role_to_enum(role),
                )
            )

        if scenario == TaskScenario.SINGLE_DOC_PARSE:
            for _, file_path, file_name, _ in saved_docs:
                if file_name.lower().endswith(".xlsx"):
                    check_items = extract_review_check_items(file_path)
    else:
        artifact = None

    findings: list[dict] = []
    cross_doc_findings: list[dict] = []
    cross_package_compare: dict | None = None
    review_markdown: str | None = None
    review_conclusion: str | None = None

    if scenario == TaskScenario.CROSS_PACKAGE_COMPARE:
        task.current_step = "cross_package_compare"
        q1_m, q1_p, q2_m, q2_p = _split_packages(parsed_materials, evidence_pools)
        task_dir = UPLOAD_DIR / task.task_id
        docs = task.documents
        split_at = len(docs) // 2

        def _uploads_for_slice(slice_docs: list[dict]) -> list[tuple[str, bytes]]:
            out = []
            for doc in slice_docs:
                name = doc["file_name"]
                if name.startswith("~$"):
                    continue
                out.append((name, (task_dir / name).read_bytes()))
            return out

        rp_a = run_review_plus_package(
            name="q1_yutu",
            uploads=_uploads_for_slice(docs[:split_at]),
            parser_type="local",
            on_step=on_step,
        )
        rp_b = run_review_plus_package(
            name="q2_penglai",
            uploads=_uploads_for_slice(docs[split_at:]),
            parser_type="local",
            on_step=on_step,
        )
        mapped_a = map_review_plus_to_task_fields(rp_a)
        mapped_b = map_review_plus_to_task_fields(rp_b)
        cross_package_compare = compare_document_packages(q1_m, q2_m, label_a="q1", label_b="q2")
        findings = mapped_a["findings"] + mapped_b["findings"]
        cross_doc_findings = [
            *mapped_a["cross_doc_findings"],
            *mapped_b["cross_doc_findings"],
            *cross_package_compare.get("findings", []),
        ]
        review_markdown = "\n\n---\n\n".join(
            part
            for part in [
                mapped_a["review_report_markdown"],
                mapped_b["review_report_markdown"],
            ]
            if part
        )
        review_conclusion = (
            f"跨包对比：{cross_package_compare.get('spacecraft_a')} vs "
            f"{cross_package_compare.get('spacecraft_b')}；"
            f"共享主题 {len(cross_package_compare.get('shared_topics', []))} 项。"
        )
        check_items = mapped_a["check_items"] + mapped_b["check_items"]

    elif scenario == TaskScenario.PACKAGE_REVIEW:
        task.current_step = "review_plus_workflow"
        uploads = []
        task_dir = UPLOAD_DIR / task.task_id
        for doc in task.documents:
            file_name = doc["file_name"]
            if file_name.startswith("~$"):
                continue
            path = task_dir / file_name
            uploads.append((file_name, path.read_bytes()))
        rp_task = run_review_plus_package(
            name=task.package_id or task.task_description or "package_review",
            uploads=uploads,
            parser_type="local",
            on_step=on_step,
        )
        mapped = map_review_plus_to_task_fields(rp_task)
        findings = mapped["findings"]
        cross_doc_findings = mapped["cross_doc_findings"]
        review_markdown = mapped["review_report_markdown"]
        review_conclusion = mapped["review_conclusion"]
        check_items = mapped["check_items"]

    task.current_step = "finalize"
    task.progress = 0.98
    task.parser_trace = parser_trace

    if artifact is not None:
        parse_artifact = artifact.model_dump(mode="json")
        parse_file_results = parse_artifact.get("file_results") or []
        parse_batch_summary = parse_artifact.get("batch_summary") or {}
    else:
        parse_file_results = []
        parse_batch_summary = {
            "file_count": 0,
            "parsed_count": 0,
            "degraded_count": 0,
            "failed_count": 0,
            "execution_pass_rate": 0.0,
            "capability_pass_rate": 0.0,
            "degradation_rate": 0.0,
        }
        parse_artifact = {
            "artifact_id": f"task-{task.task_id}",
            "file_results": parse_file_results,
            "batch_summary": parse_batch_summary,
            "document_ir": {},
            "section_tree": {},
            "evidence_pool": {},
            "extracted_parameters": extracted_parameters,
            "extracted_objects": extracted_objects,
            "trace_link_candidates": trace_link_candidates,
            "parse_quality_report": {
                "status": "ok",
                "warnings": warnings,
                "execution_pass_rate": 0.0,
                "capability_pass_rate": 0.0,
                "degradation_rate": 0.0,
            },
        }

    execution_metrics_snapshot = build_execution_metrics_snapshot(
        task_result={
            "structured_output": {
                "parse_artifact": parse_artifact,
                "batch_summary": parse_batch_summary,
            }
        }
    )
    parser_trace_summary = build_parser_trace_summary(
        parse_artifact=parse_artifact,
        parser_traces=parser_trace,
    )

    result = StructuredTaskResult(
        scenario=scenario,
        package_id=task.package_id,
        materials=materials,
        check_items=check_items,
        findings=findings,
        cross_doc_findings=cross_doc_findings,
        review_report_markdown=review_markdown,
        review_conclusion=review_conclusion,
        cross_package_compare=cross_package_compare,
        tdms_metadata=tdms_metadata,
        structured_output={
            "materials": [m.model_dump() for m in materials],
            "check_items": [c.model_dump() for c in check_items],
            "findings": findings,
            "cross_doc_findings": cross_doc_findings,
            "cross_package_compare": cross_package_compare,
            "tdms_metadata": tdms_metadata,
            "extracted_parameters": extracted_parameters,
            "extracted_objects": extracted_objects,
            "trace_link_candidates": trace_link_candidates,
            "traceability_summaries": traceability_summaries,
            "document_ir": document_irs,
            "parse_artifact": parse_artifact,
            "file_results": parse_file_results,
            "batch_summary": parse_batch_summary,
            "execution_metrics_snapshot": execution_metrics_snapshot,
            "parser_trace_summary": parser_trace_summary,
            "conclusion": review_conclusion,
        },
        markdown_output=review_markdown or ("\n\n---\n\n".join(markdown_parts) if markdown_parts else None),
        section_trees=section_trees,
        evidence_pools=evidence_pools,
        warnings=warnings,
        parser_trace=parser_trace,
    )
    return result.model_dump(mode="json")
