from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List


def write_run_artifacts(
    *,
    config: Dict[str, Any],
    file_path: Path,
    payload: Dict[str, Any],
    prompt_text: str,
    raw_response: str,
) -> None:
    """Write latest and history artifacts for auditability of the data base."""
    paths = config["paths"]
    Path(paths["last_prompt_file"]).write_text(prompt_text, encoding="utf-8")
    Path(paths["last_response_file"]).write_text(raw_response, encoding="utf-8")
    Path(paths["last_run_file"]).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    Path(paths["last_log_file"]).write_text(format_run_log(payload), encoding="utf-8")
    stem = file_path.stem.replace(" ", "_")
    short_run = str(dict(payload.get("run_meta", {}) or {}).get("run_id", ""))[:8]
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    history_dir = Path(paths["logs_history_dir"])
    history_dir.mkdir(parents=True, exist_ok=True)
    (history_dir / f"{ts}_{stem}_{short_run}_llm_prompt.txt").write_text(prompt_text, encoding="utf-8")
    (history_dir / f"{ts}_{stem}_{short_run}_llm_response.txt").write_text(raw_response, encoding="utf-8")
    (history_dir / f"{ts}_{stem}_{short_run}_run.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (history_dir / f"{ts}_{stem}_{short_run}_run_log.txt").write_text(format_run_log(payload), encoding="utf-8")


def format_run_log(payload: Dict[str, Any]) -> str:
    run_meta = dict(payload.get("run_meta", {}) or {})
    lines: List[str] = []
    lines.append(f"run_id: {run_meta.get('run_id', '')}")
    lines.append(f"resume_identity: {run_meta.get('resume_identity', '')}")
    lines.append(f"source_path: {run_meta.get('source_path', '')}")
    lines.append(f"parser_mode: {run_meta.get('parser_mode', '')}")
    lines.append(f"resolve_mode: {run_meta.get('resolve_mode', '')}")
    lines.append(f"project_boundary_mode: {run_meta.get('project_boundary_mode', '')}")
    lines.append(f"compression_ratio: {run_meta.get('compression_ratio', 0.0)}")
    profile = dict(payload.get("document_profile", {}) or {})
    lines.append(f"document_profile: {profile.get('value', '')} confidence={profile.get('confidence', 0.0)}")
    candidate_profile = dict(payload.get("candidate_profile", {}) or {})
    name = dict(candidate_profile.get("name", {}) or {}).get("value", "")
    lines.append(f"name: {name}")
    lines.append(f"work_count: {len(payload.get('work_experiences', []) or [])}")
    lines.append(f"education_count: {len(payload.get('education_experiences', []) or [])}")
    lines.append(f"project_count: {payload.get('project_count', len(payload.get('project_chunks', []) or []))}")
    lines.append(f"project_chunk_count: {len(payload.get('project_chunks', []) or [])}")
    storage_gate = dict(payload.get("storage_gate", {}) or {})
    if storage_gate:
        lines.append(f"storage_gate: {json.dumps(storage_gate, ensure_ascii=False)}")
    validation_summary = dict(payload.get("validation_summary", {}) or {})
    lines.append(f"validation_summary: {json.dumps(validation_summary, ensure_ascii=False)}")
    storage_summary = dict(payload.get("storage_summary", {}) or {})
    lines.append("")
    lines.append("[resume_preview]")
    lines.append(f"contact: {json.dumps(dict(candidate_profile.get('contact', {}) or {}), ensure_ascii=False)}")
    lines.append(f"work_experiences: {len(payload.get('work_experiences', []) or [])}")
    for row in list(payload.get("work_experiences", []) or [])[:6]:
        lines.append(
            f"- {row.get('work_ref', '')}: {row.get('company_name', '')} | {row.get('job_title_raw', '')} | "
            f"{row.get('start_date', '')}->{row.get('end_date', '')}"
        )
    lines.append(f"education_experiences: {len(payload.get('education_experiences', []) or [])}")
    for row in list(payload.get("education_experiences", []) or [])[:6]:
        lines.append(
            f"- {row.get('school_name', '')} | {row.get('degree', '')} | {row.get('start_date', '')}->{row.get('end_date', '')}"
        )
    lines.append(f"projects: {payload.get('project_count', len(payload.get('project_chunks', []) or []))}")
    lines.append(f"project_candidates: {len(payload.get('project_chunks', []) or [])}")
    for row in list(payload.get("project_chunks", []) or [])[:8]:
        evidence_ids = list(dict(row.get("evidence", {}) or {}).get("block_ids", []) or [])
        lines.append(
            f"- candidate {row.get('chunk_id', '')}: {row.get('project_title', '')} | "
            f"type={row.get('candidate_type', '')} | evidence_count={len(evidence_ids)}"
        )
    for row in list(payload.get("projects", []) or [])[:8]:
        lines.append(
            f"- {row.get('project_name_raw', '')} | {row.get('project_source_type', '')} | "
            f"evidence={list(row.get('evidence_block_ids', []) or [])}"
        )
    if storage_summary:
        lines.extend(_format_storage_summary(storage_summary))
    return "\n".join(lines)


def _format_storage_summary(storage_summary: Dict[str, Any]) -> List[str]:
    lines: List[str] = []
    lines.append("")
    lines.append("[structured_store]")
    candidate = dict(storage_summary.get("candidate_row", {}) or {})
    lines.append(json.dumps(candidate, ensure_ascii=False, indent=2))
    work_rows = list(storage_summary.get("work_rows", []) or [])
    education_rows = list(storage_summary.get("education_rows", []) or [])
    tag_rows = list(storage_summary.get("tag_rows", []) or [])
    project_manifest_rows = list(storage_summary.get("project_manifest_rows", []) or [])
    project_tag_rows = list(storage_summary.get("project_tag_rows", []) or [])
    lines.append(f"work_rows_count: {len(work_rows)}")
    for row in work_rows:
        lines.append(json.dumps(row, ensure_ascii=False, indent=2))
    lines.append(f"education_rows_count: {len(education_rows)}")
    for row in education_rows:
        lines.append(json.dumps(row, ensure_ascii=False, indent=2))
    lines.append(f"tag_rows_count: {len(tag_rows)}")
    for row in tag_rows:
        lines.append(json.dumps(row, ensure_ascii=False, indent=2))
    lines.append(f"project_manifest_rows_count: {len(project_manifest_rows)}")
    for row in project_manifest_rows:
        lines.append(json.dumps(row, ensure_ascii=False, indent=2))
    lines.append(f"project_tag_rows_count: {len(project_tag_rows)}")
    for row in project_tag_rows:
        lines.append(json.dumps(row, ensure_ascii=False, indent=2))
    lines.append("")
    lines.append("[vector_store]")
    vector_rows = list(storage_summary.get("vector_rows", []) or [])
    lines.append(f"project_chunks_prepared_count: {storage_summary.get('project_chunks_prepared_count', 0)}")
    lines.append(f"vector_rows_skipped_no_embedding: {storage_summary.get('vector_rows_skipped_no_embedding', 0)}")
    lines.append(f"vector_rows_count: {len(vector_rows)}")
    for row in vector_rows:
        lines.append(json.dumps(row, ensure_ascii=False, indent=2))
    return lines
