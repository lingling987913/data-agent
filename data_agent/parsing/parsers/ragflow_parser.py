"""RAGFlow API parser (currently unused in main parse path)."""

from __future__ import annotations

import os
import time
import uuid

from data_agent.parsing.schemas import ParsedDocument, ParsedDocumentBlock


def parse_via_ragflow(file_path: str, file_name: str, parsed_doc: ParsedDocument) -> None:
    parsed_doc.parser_name = "ragflow_api"
    from aq_core.infra.config import get_config_service
    import httpx

    config = get_config_service()
    if not config.ragflow_api_url or not config.ragflow_api_key:
        parsed_doc.parse_status = "failed"
        parsed_doc.warnings.append("RAGFlow configuration missing in environment.")
        return

    dataset_id = os.getenv("RAGFLOW_GNC_REVIEW_DATASET_ID")

    if not dataset_id:
        parsed_doc.parse_status = "failed"
        parsed_doc.warnings.append("No RAGFlow dataset ID configured for uploading.")
        return

    base_url = config.ragflow_api_url.rstrip('/')
    headers = {"Authorization": f"Bearer {config.ragflow_api_key}"}

    try:
        with httpx.Client(timeout=120.0) as client:
            with open(file_path, 'rb') as f:
                files = {'file': (file_name, f)}
                upload_data = {"dataset_id": dataset_id}
                resp = client.post(f"{base_url}/api/v1/dataset/{dataset_id}/document", headers=headers, files=files, data=upload_data)
                resp.raise_for_status()

            resp_data = resp.json()
            if resp_data.get("code") != 0:
                raise Exception(f"Upload failed: {resp_data.get('message')}")

            docs = resp_data.get("data", [])
            if not docs:
                raise Exception("Upload returned empty document list.")
            doc_info = docs[0] if isinstance(docs, list) else docs
            doc_id = doc_info.get("id")

            run_resp = client.post(f"{base_url}/api/v1/document/run", headers=headers, json={"document_ids": [doc_id], "run": 1})
            run_resp.raise_for_status()

            for _ in range(30):
                stat_resp = client.get(f"{base_url}/api/v1/dataset/{dataset_id}/documents", headers=headers, params={"id": doc_id, "page": 1, "page_size": 1})
                stat_data = stat_resp.json().get("data", {}).get("docs", [])
                if not stat_data:
                    break
                doc_stat = stat_data[0]
                status = str(doc_stat.get("run", ""))
                if status == "3":
                    break
                elif status == "4":
                    raise Exception("RAGFlow Parsing failed on server side.")
                time.sleep(2)
            else:
                parsed_doc.warnings.append("RAGFlow Parsing timeout (waited 60 seconds). Chunks might be incomplete.")

            chunk_resp = client.get(f"{base_url}/api/v1/document/{doc_id}/chunks", headers=headers, params={"page": 1, "page_size": 1000})
            chunk_resp.raise_for_status()
            chunks_data = chunk_resp.json().get("data", {}).get("chunks", [])
            if not chunks_data and "data" in chunk_resp.json() and isinstance(chunk_resp.json()["data"], list):
                chunks_data = chunk_resp.json()["data"]

            blocks = []
            for c in chunks_data:
                content = c.get("content_with_weight") or c.get("content") or c.get("text") or ""
                if content:
                    blocks.append(ParsedDocumentBlock(
                        block_id=str(uuid.uuid4()),
                        block_type="paragraph",
                        text=content.strip(),
                        order_index=len(blocks)
                    ))

            if not blocks:
                raise Exception("RAGFlow returned no chunks. Parse might still be running or file is empty.")

            parsed_doc.blocks = blocks

    except Exception as e:
        parsed_doc.parse_status = "failed"
        parsed_doc.warnings.append(f"RAGFlow Integration failed: {str(e)}")
