from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple
from uuid import uuid4

from .llm.checker import build_project_chunks_from_rule_candidates, run_llm_check, run_llm_project_repair
from .llm.prompts import build_project_repair_prompt, build_resume_check_prompt
from .pipeline_yaml import (
    load_chunking_config,
    load_concepts,
    load_domain_configs,
    load_routing_config,
    load_section_aliases,
    load_validate_config,
    merge_global_and_domain_local_concepts,
)
from .runtime.document_parser import parse_resume_to_blocks_with_diagnostics
from .runtime.rule_matcher import build_rule_candidates
from .runtime.validator import validate_resume_payload
from .storage.backends import build_structured_backend, build_vector_backend
from .storage.job_store import PipelineJobStore
from .storage.vector_indexer import build_vector_payload


def run_ingestion_pipeline(*, file_path: Path, config: Dict[str, Any], progress_callback: Callable[[str], None] | None = None) -> Dict[str, Any]:
    _ensure_directories(config)
    run_id = uuid4().hex
    resume_identity = _compute_resume_identity(file_path)
    job_store = PipelineJobStore(Path(config["paths"]["jobs_db"]))
    job_store.mark_started(run_id=run_id, resume_identity=resume_identity, source_path=str(file_path))
    parser_mode = "unknown"
    resolve_mode = "rule_fallback"
    prompt_text = ""
    raw_response = ""
    try:
        _progress(progress_callback, "1/6 parse resume blocks")
        blocks, parser_diag = parse_resume_to_blocks_with_diagnostics(file_path, config)
        parser_mode = str(parser_diag.get("parser_mode", "builtin"))
        _progress(progress_callback, f"parser={parser_mode} blocks={len(blocks)}")
        section_config = load_section_aliases(Path(config["paths"]["section_aliases_file"]))
        routing_config = load_routing_config(Path(config["paths"]["routing_file"]))
        chunking_config = load_chunking_config(Path(config["paths"]["chunking_file"]))
        validate_config = load_validate_config(Path(config["paths"]["validate_file"]))
        global_concepts = load_concepts(Path(config["paths"]["global_concepts_file"]))
        domains = load_domain_configs(Path(config["paths"]["domains_dir"]))
        merged_concepts = merge_global_and_domain_local_concepts(global_concepts, domains)
        _progress(progress_callback, "2/6 build rule candidates")
        rule_payload = build_rule_candidates(
            blocks=blocks,
            file_path=file_path,
            section_config=section_config,
            routing_config=routing_config,
            chunking_config=chunking_config,
            concepts=merged_concepts,
            domains=domains,
        )
        _progress(
            progress_callback,
            "rule profile="
            f"{dict(rule_payload.get('document_profile', {}) or {}).get('value', '')} "
            f"work={len(rule_payload.get('work_experiences', []) or [])} "
            f"education={len(rule_payload.get('education_experiences', []) or [])} "
            f"project_candidates={len(rule_payload.get('project_candidate_groups', []) or [])}",
        )
        project_boundary_quality = dict(rule_payload.get("project_boundary_quality", {}) or {})
        repair_required = project_boundary_quality.get("status") == "repair_required"
        prompt_text = (
            build_project_repair_prompt(rule_payload=rule_payload, config=config)
            if repair_required
            else build_resume_check_prompt(rule_payload=rule_payload, config=config)
        )
        llm_payload = None
        fallback_reason = ""
        try:
            if repair_required:
                _progress(progress_callback, "3/6 llm project boundary repair")
                llm_payload = run_llm_project_repair(rule_payload, config, prompt_text=prompt_text)
            else:
                _progress(progress_callback, "3/6 llm boundary check")
                llm_payload = run_llm_check(rule_payload, config, prompt_text=prompt_text)
            prompt_text = str(llm_payload.get("llm_prompt", ""))
            raw_response = str(llm_payload.get("raw_response", ""))
            resolve_mode = str(llm_payload.get("resolve_mode", "") or "llm_success")
            _progress(progress_callback, resolve_mode)
        except Exception as error:
            fallback_reason = f"{type(error).__name__}: {error}"
            raw_response = f"fallback due to: {error}"
            llm_payload = {
                **build_project_chunks_from_rule_candidates(rule_payload),
                "resolve_mode": "rule_fallback",
                "fallback_reason": fallback_reason,
                "llm_prompt": prompt_text,
                "raw_response": raw_response,
                "project_boundary_mode": "repair_failed" if repair_required else "normal_failed",
            }
            resolve_mode = "rule_fallback"
            _progress(progress_callback, f"rule_fallback reason={type(error).__name__}")
        payload = _assemble_output(
            file_path=file_path,
            run_id=run_id,
            resume_identity=resume_identity,
            parser_diag=parser_diag,
            rule_payload=rule_payload,
            llm_payload=llm_payload,
            resolve_mode=resolve_mode,
        )
        _progress(progress_callback, "4/6 validate result")
        validated = validate_resume_payload(
            payload=payload,
            validate_config=validate_config,
            allowed_concepts=set(merged_concepts.keys()),
            allowed_domains=set(domains.keys()),
        )
        _progress(progress_callback, "5/6 write SQL rows and Chroma vectors")
        storage_payload = _apply_storage_quality_gate(validated)
        structured_backend = build_structured_backend(config)
        vector_backend = build_vector_backend(config)
        replaced_existing = structured_backend.upsert(storage_payload)
        chunk_vectors = build_vector_payload(
            chunk_payloads=storage_payload.get("project_chunks", []) or [],
            config=config,
            resume_identity=resume_identity,
        )
        vector_backend.replace_resume_chunk_vectors(resume_identity, chunk_vectors)
        validated["run_meta"]["replaced_existing_resume"] = replaced_existing
        validated["run_meta"]["prior_run_count"] = job_store.count_runs_for_resume(resume_identity)
        validated["storage_gate"] = dict(storage_payload.get("storage_gate", {}) or {})
        validated["project_count_for_storage"] = int(storage_payload.get("project_count_for_storage", 0) or 0)
        validated["storage_summary"] = _build_storage_summary(storage_payload, chunk_vectors)
        _progress(
            progress_callback,
            "storage "
            f"project_rows={len(validated['storage_summary'].get('project_manifest_rows', []) or [])} "
            f"vector_rows={len(validated['storage_summary'].get('vector_rows', []) or [])} "
            f"blocked={validated['storage_gate'].get('storage_blocked_reason', '')}",
        )
        _progress(progress_callback, "6/6 write latest/history logs")
        _write_run_artifacts(
            config=config,
            file_path=file_path,
            payload=validated,
            prompt_text=prompt_text,
            raw_response=raw_response,
        )
        job_store.mark_finished(run_id=run_id, status="SUCCEEDED", parser_mode=parser_mode, resolve_mode=resolve_mode)
        return validated
    except Exception as error:
        job_store.mark_finished(
            run_id=run_id,
            status="FAILED",
            parser_mode=parser_mode,
            resolve_mode=resolve_mode,
            error_message=f"{type(error).__name__}: {error}",
        )
        raise


def _progress(callback: Callable[[str], None] | None, message: str) -> None:
    if callback is not None:
        callback(message)


def _assemble_output(
    *,
    file_path: Path,
    run_id: str,
    resume_identity: str,
    parser_diag: Dict[str, Any],
    rule_payload: Dict[str, Any],
    llm_payload: Dict[str, Any],
    resolve_mode: str,
) -> Dict[str, Any]:
    document_profile = dict(llm_payload.get("document_profile", {}) or {})
    candidate_profile = dict(llm_payload.get("candidate_profile", {}) or {})
    return {
        "run_meta": {
            "run_id": run_id,
            "resume_identity": resume_identity,
            "source_path": str(file_path),
            "parser_mode": str(parser_diag.get("parser_mode", "")),
            "parser_fallback_reason": str(parser_diag.get("parser_fallback_reason", "")),
            "resolve_mode": resolve_mode,
            "fallback_reason": str(llm_payload.get("fallback_reason", "")),
            "project_boundary_mode": str(llm_payload.get("project_boundary_mode", "normal" if resolve_mode == "llm_success" else "")),
            "compression_ratio": float(rule_payload.get("compression_ratio", 0.0) or 0.0),
            "timestamp": datetime.now().isoformat(timespec="seconds"),
        },
        "document_profile": document_profile,
        "candidate_profile": candidate_profile,
        "work_experiences": list(llm_payload.get("work_experiences", []) or []),
        "education_experiences": list(llm_payload.get("education_experiences", []) or []),
        "concept_tags": list(llm_payload.get("concept_tags", []) or []),
        "domain_tags": list(llm_payload.get("domain_tags", []) or []),
        "experience_tags": list(llm_payload.get("experience_tags", []) or rule_payload.get("experience_tags", []) or []),
        "skill_tags": list(llm_payload.get("skill_tags", []) or []),
        "project_count": len(llm_payload.get("projects", []) or []) or len(llm_payload.get("project_chunks", []) or []),
        "projects": list(llm_payload.get("projects", []) or []),
        "project_chunks": list(llm_payload.get("project_chunks", []) or []),
        "diagnostics": {
            "selected_blocks": list(rule_payload.get("selected_blocks", []) or []),
            "dropped_blocks": list(rule_payload.get("dropped_blocks", []) or []),
            "block_actions": list(rule_payload.get("block_actions", []) or []),
            "project_candidate_groups": list(rule_payload.get("project_candidate_groups", []) or []),
            "project_section_blocks": list(rule_payload.get("project_section_blocks", []) or []),
            "project_repair_blocks": list(rule_payload.get("project_repair_blocks", []) or []),
            "project_boundary_quality": dict(rule_payload.get("project_boundary_quality", {}) or {}),
            "project_boundary_mode": str(llm_payload.get("project_boundary_mode", "normal" if resolve_mode == "llm_success" else "")),
            "llm_prompt": str(llm_payload.get("llm_prompt", "")),
            "raw_response": str(llm_payload.get("raw_response", "")),
        },
    }


def _compute_resume_identity(file_path: Path) -> str:
    data = file_path.read_bytes()
    return hashlib.sha256(data).hexdigest()


def _apply_storage_quality_gate(payload: Dict[str, Any]) -> Dict[str, Any]:
    gated = {**payload}
    run_meta = dict(gated.get("run_meta", {}) or {})
    resolve_mode = str(run_meta.get("resolve_mode", "")).strip()
    project_chunks = list(gated.get("project_chunks", []) or [])
    projects = list(gated.get("projects", []) or [])
    storage_gate = {
        "project_storage_allowed": True,
        "storage_blocked_reason": "",
        "project_boundary_status": resolve_mode if resolve_mode in {"llm_success", "llm_repair_success"} else "",
        "project_chunks_before_gate": len(project_chunks),
        "projects_before_gate": len(projects),
    }
    if resolve_mode not in {"llm_success", "llm_repair_success"}:
        if _has_trusted_rule_grouping(project_chunks, projects):
            storage_gate["project_storage_allowed"] = True
            storage_gate["project_boundary_status"] = "trusted_rule_grouping"
        else:
            storage_gate["project_storage_allowed"] = False
            storage_gate["project_boundary_status"] = "untrusted_rule_grouping"
            storage_gate["storage_blocked_reason"] = "project_boundary_not_trusted"
    elif len(project_chunks) > int(gated.get("project_count", len(project_chunks)) or len(project_chunks)) + 4 and len(project_chunks) > 8:
        storage_gate["project_storage_allowed"] = False
        storage_gate["storage_blocked_reason"] = "low_quality_project_boundary"
    if not storage_gate["project_storage_allowed"]:
        gated["projects"] = []
        gated["project_chunks"] = []
        gated["project_count_for_storage"] = 0
    else:
        gated["projects"] = _dedupe_projects_for_storage(projects)
        gated["project_chunks"] = _dedupe_project_chunks_for_storage(project_chunks)
        gated["project_count_for_storage"] = len(gated["projects"]) or len(gated["project_chunks"])
    storage_gate["project_chunks_after_gate"] = len(gated.get("project_chunks", []) or [])
    storage_gate["projects_after_gate"] = len(gated.get("projects", []) or [])
    gated["storage_gate"] = storage_gate
    return gated


def _has_trusted_rule_grouping(project_chunks: List[Dict[str, Any]], projects: List[Dict[str, Any]]) -> bool:
    if not project_chunks or len(project_chunks) > 8:
        return False
    deduped_chunks = _dedupe_project_chunks_for_storage(project_chunks)
    deduped_projects = _dedupe_projects_for_storage(projects)
    if not deduped_projects:
        return all(_is_trusted_rule_chunk(item) for item in deduped_chunks)
    if not _project_counts_are_explainable(deduped_chunks, deduped_projects):
        return False
    project_titles = {_normalize_storage_key(str(item.get("project_name_raw", "") or "")) for item in deduped_projects}
    project_evidence_sets = {
        tuple(sorted(str(block_id).strip() for block_id in list(item.get("evidence_block_ids", []) or []) if str(block_id).strip()))
        for item in deduped_projects
    }
    for item in deduped_chunks:
        evidence_ids = list(dict(item.get("evidence", {}) or {}).get("block_ids", []) or [])
        title = str(item.get("project_title", "") or item.get("chunk_title", "")).strip()
        if not _is_trusted_rule_chunk(item):
            return False
        evidence_key = tuple(sorted(str(block_id).strip() for block_id in evidence_ids if str(block_id).strip()))
        if _normalize_storage_key(title) not in project_titles and evidence_key not in project_evidence_sets:
            return False
    return True


def _is_trusted_rule_chunk(item: Dict[str, Any]) -> bool:
    trusted_types = {"work_scope_group", "work_embedded_project_title", "standalone_project_title"}
    candidate_type = str(item.get("candidate_type", "")).strip()
    title = str(item.get("project_title", "") or item.get("chunk_title", "")).strip()
    evidence_ids = list(dict(item.get("evidence", {}) or {}).get("block_ids", []) or [])
    if candidate_type not in trusted_types or not title:
        return False
    if candidate_type == "standalone_project_title" and evidence_ids:
        return True
    if len(evidence_ids) < 2:
        return False
    return True


def _project_counts_are_explainable(project_chunks: List[Dict[str, Any]], projects: List[Dict[str, Any]]) -> bool:
    chunk_count = len(project_chunks)
    project_count = len(projects)
    if chunk_count <= 0 or project_count <= 0:
        return False
    if chunk_count == project_count:
        return True
    chunk_titles = {_normalize_storage_key(str(item.get("project_title", "") or item.get("chunk_title", "") or "")) for item in project_chunks}
    project_titles = {_normalize_storage_key(str(item.get("project_name_raw", "") or "")) for item in projects}
    if chunk_titles and project_titles and chunk_titles == project_titles:
        return True
    chunk_evidence = {
        tuple(sorted(str(block_id).strip() for block_id in list(dict(item.get("evidence", {}) or {}).get("block_ids", []) or []) if str(block_id).strip()))
        for item in project_chunks
    }
    project_evidence = {
        tuple(sorted(str(block_id).strip() for block_id in list(item.get("evidence_block_ids", []) or []) if str(block_id).strip()))
        for item in projects
    }
    return bool(chunk_evidence) and chunk_evidence == project_evidence


def _dedupe_projects_for_storage(projects: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    output: List[Dict[str, Any]] = []
    for item in projects:
        key = _project_storage_key(
            title=str(item.get("project_name_raw", "") or ""),
            organization=str(item.get("organization_raw", "") or ""),
            date_range=str(item.get("project_date_range_raw", "") or item.get("date_range_raw", "") or ""),
            role=str(item.get("role_raw", "") or item.get("role_normalized", "") or ""),
            evidence_ids=list(item.get("evidence_block_ids", []) or []),
        )
        if key in seen:
            continue
        seen.add(key)
        output.append(item)
    return output


def _dedupe_project_chunks_for_storage(project_chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    output: List[Dict[str, Any]] = []
    for item in project_chunks:
        evidence = dict(item.get("evidence", {}) or {})
        key = _project_storage_key(
            title=str(item.get("project_title", "") or item.get("chunk_title", "") or ""),
            organization=str(item.get("organization_raw", "") or ""),
            date_range=str(item.get("date_range_raw", "") or ""),
            role=str(item.get("role_raw", "") or item.get("role_normalized", "") or ""),
            evidence_ids=list(evidence.get("block_ids", []) or []),
        )
        if key in seen:
            continue
        seen.add(key)
        output.append(item)
    return output


def _project_storage_key(*, title: str, organization: str, date_range: str, role: str, evidence_ids: List[str]) -> Tuple[str, str, str, str, Tuple[str, ...]]:
    return (
        _normalize_storage_key(title),
        _normalize_storage_key(organization),
        _normalize_storage_key(date_range),
        _normalize_storage_key(role),
        tuple(sorted(str(item).strip() for item in evidence_ids if str(item).strip())),
    )


def _normalize_storage_key(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "")).lower()


def _ensure_directories(config: Dict[str, Any]) -> None:
    for key, value in config.get("paths", {}).items():
        path = Path(value)
        if path.suffix:
            path.parent.mkdir(parents=True, exist_ok=True)
        else:
            path.mkdir(parents=True, exist_ok=True)


def _write_run_artifacts(
    *,
    config: Dict[str, Any],
    file_path: Path,
    payload: Dict[str, Any],
    prompt_text: str,
    raw_response: str,
) -> None:
    paths = config["paths"]
    Path(paths["last_prompt_file"]).write_text(prompt_text, encoding="utf-8")
    Path(paths["last_response_file"]).write_text(raw_response, encoding="utf-8")
    Path(paths["last_run_file"]).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    Path(paths["last_log_file"]).write_text(_format_run_log(payload), encoding="utf-8")
    stem = file_path.stem.replace(" ", "_")
    short_run = str(dict(payload.get("run_meta", {}) or {}).get("run_id", ""))[:8]
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    history_dir = Path(paths["logs_history_dir"])
    history_dir.mkdir(parents=True, exist_ok=True)
    (history_dir / f"{ts}_{stem}_{short_run}_llm_prompt.txt").write_text(prompt_text, encoding="utf-8")
    (history_dir / f"{ts}_{stem}_{short_run}_llm_response.txt").write_text(raw_response, encoding="utf-8")
    (history_dir / f"{ts}_{stem}_{short_run}_run.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (history_dir / f"{ts}_{stem}_{short_run}_run_log.txt").write_text(_format_run_log(payload), encoding="utf-8")


def _format_run_log(payload: Dict[str, Any]) -> str:
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
    return "\n".join(lines)


def _build_storage_summary(payload: Dict[str, Any], chunk_vectors: List[Dict[str, Any]]) -> Dict[str, Any]:
    run_meta = dict(payload.get("run_meta", {}) or {})
    candidate_profile = dict(payload.get("candidate_profile", {}) or {})
    contact = dict(candidate_profile.get("contact", {}) or {})
    candidate_row = {
        "run_id": run_meta.get("run_id", ""),
        "resume_identity": run_meta.get("resume_identity", ""),
        "source_path": run_meta.get("source_path", ""),
        "name": dict(candidate_profile.get("name", {}) or {}).get("value", ""),
        "phone": dict(contact.get("phone", {}) or {}).get("value", ""),
        "email": dict(contact.get("email", {}) or {}).get("value", ""),
        "wechat": dict(contact.get("wechat", {}) or {}).get("value", ""),
        "job_intent": dict(candidate_profile.get("job_intent", {}) or {}).get("value", ""),
        "location_raw": dict(candidate_profile.get("location_raw", {}) or {}).get("value", ""),
        "overview_raw": dict(candidate_profile.get("overview_raw", {}) or {}).get("value", ""),
        "document_profile": dict(payload.get("document_profile", {}) or {}).get("value", ""),
        "resolve_mode": run_meta.get("resolve_mode", ""),
        "compression_ratio": run_meta.get("compression_ratio", 0.0),
    }
    work_rows = [
        {
            "work_ref": row.get("work_ref", ""),
            "company_name": row.get("company_name", ""),
            "job_title_raw": row.get("job_title_raw", ""),
            "start_date": row.get("start_date", ""),
            "end_date": row.get("end_date", ""),
            "location": row.get("location", ""),
            "confidence": row.get("confidence", 0.0),
            "source": row.get("source", ""),
            "evidence_block_ids": list(dict(row.get("evidence", {}) or {}).get("block_ids", []) or []),
        }
        for row in list(payload.get("work_experiences", []) or [])
    ]
    education_rows = [
        {
            "school_name": row.get("school_name", ""),
            "degree": row.get("degree", ""),
            "major": row.get("major", ""),
            "start_date": row.get("start_date", ""),
            "end_date": row.get("end_date", ""),
            "confidence": row.get("confidence", 0.0),
            "source": row.get("source", ""),
            "evidence_block_ids": list(dict(row.get("evidence", {}) or {}).get("block_ids", []) or []),
        }
        for row in list(payload.get("education_experiences", []) or [])
    ]
    tag_rows: List[Dict[str, Any]] = []
    for tag_type in ("concept_tags", "domain_tags", "skill_tags"):
        for row in list(payload.get(tag_type, []) or []):
            tag_rows.append(
                {
                    "tag_type": tag_type.replace("_tags", ""),
                    "tag_value": row.get("value", ""),
                    "confidence": row.get("confidence", 0.0),
                    "source": row.get("source", ""),
                    "evidence_block_ids": list(dict(row.get("evidence", {}) or {}).get("block_ids", []) or []),
                }
            )
    profile_skills = dict(candidate_profile.get("resume_level_skills", {}) or {})
    for item in list(profile_skills.get("normalized", []) or []):
        if isinstance(item, dict):
            tag_rows.append(
                {
                    "tag_type": "skill",
                    "tag_value": item.get("value", ""),
                    "confidence": item.get("confidence", 0.0),
                    "source": item.get("source", ""),
                    "evidence_block_ids": list(dict(item.get("evidence", {}) or {}).get("block_ids", []) or []),
                }
            )
        elif str(item).strip():
            tag_rows.append({"tag_type": "skill", "tag_value": str(item).strip(), "confidence": 0.72, "source": "rule_merge", "evidence_block_ids": []})
    for item in list(profile_skills.get("raw", []) or []):
        if str(item).strip():
            tag_rows.append({"tag_type": "raw_skill", "tag_value": str(item).strip(), "confidence": 0.72, "source": "rule_merge", "evidence_block_ids": []})
    for field_name, tag_type in (
        ("languages", "language"),
        ("certifications_or_scores", "certification"),
        ("portfolio_links", "portfolio_link"),
    ):
        for item in list(candidate_profile.get(field_name, []) or []):
            if isinstance(item, dict):
                tag_rows.append(
                    {
                        "tag_type": tag_type,
                        "tag_value": item.get("value", ""),
                        "confidence": item.get("confidence", 0.0),
                        "source": item.get("source", ""),
                        "evidence_block_ids": list(dict(item.get("evidence", {}) or {}).get("block_ids", []) or []),
                    }
                )
            elif str(item).strip():
                tag_rows.append({"tag_type": tag_type, "tag_value": str(item).strip(), "confidence": 0.72, "source": "rule_merge", "evidence_block_ids": []})
    tag_rows = _dedupe_tag_rows(tag_rows)
    project_manifest_rows = [
        {
            "project_id": f"project_{index}",
            "project_name_raw": row.get("project_name_raw", ""),
            "project_source_type": row.get("project_source_type", ""),
            "parent_work_experience_ref": row.get("parent_work_experience_ref", ""),
            "organization_raw": row.get("organization_raw", ""),
            "date_range_raw": row.get("project_date_range_raw", ""),
            "role_raw": row.get("role_raw", ""),
            "role_normalized": row.get("role_normalized", ""),
            "source": "llm_check",
            "evidence_block_ids": list(row.get("evidence_block_ids", []) or []),
        }
        for index, row in enumerate(list(payload.get("projects", []) or []), start=1)
    ]
    if not project_manifest_rows:
        project_manifest_rows = [
            {
                "project_id": row.get("chunk_id", ""),
                "project_name_raw": row.get("project_title", ""),
                "candidate_type": row.get("candidate_type", ""),
                "project_source_type": row.get("project_source_type", ""),
                "parent_work_experience_ref": row.get("parent_work_experience_ref", ""),
                "organization_raw": row.get("organization_raw", ""),
                "date_range_raw": row.get("date_range_raw", ""),
                "role_raw": row.get("role_raw", ""),
                "role_normalized": row.get("role_normalized", ""),
                "source": row.get("source", ""),
                "evidence_block_ids": list(dict(row.get("evidence", {}) or {}).get("block_ids", []) or []),
            }
            for row in list(payload.get("project_chunks", []) or [])
        ]
    project_tag_rows: List[Dict[str, Any]] = []
    for index, row in enumerate(list(payload.get("projects", []) or []), start=1):
        project_id = f"project_{index}"
        for value in list(row.get("skill_normalized", []) or []):
            project_tag_rows.append({"project_id": project_id, "tag_type": "skill", "tag_value": value, "source": "llm_check"})
        for value in list(row.get("domain_tags", []) or []):
            project_tag_rows.append({"project_id": project_id, "tag_type": "domain", "tag_value": value, "source": "llm_check"})
        if row.get("role_normalized"):
            project_tag_rows.append({"project_id": project_id, "tag_type": "role", "tag_value": row.get("role_normalized", ""), "source": "llm_check"})
    vector_rows = []
    for row in chunk_vectors:
        embedding_dim = len(list(row.get("embedding", []) or []))
        if embedding_dim <= 0:
            continue
        vector_rows.append(
            {
            "chunk_id": row.get("chunk_id", ""),
            "vector_id": row.get("vector_id", ""),
            "resume_identity": row.get("resume_identity", ""),
            "project_id": row.get("project_id", ""),
            "candidate_type": row.get("candidate_type", ""),
                "project_title": row.get("project_title", ""),
                "project_summary": row.get("project_summary", ""),
                "source_section": row.get("source_section", ""),
                "organization_raw": row.get("organization_raw", ""),
                "date_range_raw": row.get("date_range_raw", ""),
                "embedding_model": row.get("embedding_model", ""),
                "embedding_dim": embedding_dim,
                "project_tags": [item.get("value", "") for item in list(row.get("project_tags", []) or [])],
                "evidence_block_ids": list(dict(row.get("evidence", {}) or {}).get("block_ids", []) or []),
            }
        )
    return {
        "candidate_row": candidate_row,
        "work_rows": work_rows,
        "education_rows": education_rows,
        "tag_rows": tag_rows,
        "project_manifest_rows": project_manifest_rows,
        "project_tag_rows": project_tag_rows,
        "project_chunks_prepared_count": len(chunk_vectors),
        "vector_rows_skipped_no_embedding": len(chunk_vectors) - len(vector_rows),
        "vector_rows": vector_rows,
    }


def _dedupe_tag_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    deduped: List[Dict[str, Any]] = []
    seen = set()
    for row in rows:
        key = (str(row.get("tag_type", "")).strip(), str(row.get("tag_value", "")).strip())
        if not key[0] or not key[1] or key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped
