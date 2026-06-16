from __future__ import annotations

import hashlib
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List
from uuid import uuid4

from .llm.checker import build_project_chunks_from_rule_candidates, run_llm_check, run_llm_project_repair
from .llm.prompts import build_project_repair_prompt, build_resume_check_prompt
from .pipeline_yaml import (
    ValidateConfig,
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
from .runtime.run_artifacts import write_run_artifacts
from .runtime.storage_quality import apply_storage_quality_gate
from .runtime.storage_summary import build_storage_summary
from .runtime.validator import validate_resume_payload
from .schemas import DocumentBlock
from .storage.backends import build_structured_backend, build_vector_backend
from .storage.job_store import PipelineJobStore
from .storage.vector_indexer import build_vector_payload


def run_ingestion_pipeline(*, file_path: Path, config: Dict[str, Any], progress_callback: Callable[[str], None] | None = None) -> Dict[str, Any]:
    """Run the v3 data-base ingestion chain.

    The pipeline is intentionally framed as data nodes: each node produces a
    durable, auditable intermediate that protects data accuracy before storage.
    """
    _ensure_directories(config)
    run_id = uuid4().hex
    document_hash = _compute_document_hash(file_path)
    resume_identity = document_hash
    job_store = PipelineJobStore(Path(config["paths"]["jobs_db"]))
    job_store.mark_started(run_id=run_id, resume_identity=resume_identity, source_path=str(file_path))
    parser_mode = "unknown"
    resolve_mode = "rule_fallback"
    try:
        blocks, parser_diag = _parse_resume_node(file_path=file_path, config=config, progress_callback=progress_callback)
        parser_mode = str(parser_diag.get("parser_mode", "builtin"))

        rule_result = _build_rule_candidates_node(
            blocks=blocks,
            file_path=file_path,
            config=config,
            progress_callback=progress_callback,
        )
        rule_payload = rule_result["rule_payload"]

        llm_result = _resolve_with_llm_or_rule_fallback_node(
            rule_payload=rule_payload,
            config=config,
            progress_callback=progress_callback,
        )
        llm_payload = llm_result["llm_payload"]
        resolve_mode = str(llm_result["resolve_mode"])

        payload = _assemble_output(
            file_path=file_path,
            run_id=run_id,
            resume_identity=resume_identity,
            document_hash=document_hash,
            parser_diag=parser_diag,
            rule_payload=rule_payload,
            llm_payload=llm_payload,
            resolve_mode=resolve_mode,
        )
        payload = _resolve_candidate_identity_node(payload=payload, config=config, progress_callback=progress_callback)
        resume_identity = str(dict(payload.get("run_meta", {}) or {}).get("resume_identity", "") or resume_identity)
        job_store.mark_started(run_id=run_id, resume_identity=resume_identity, source_path=str(file_path))
        validated = _validate_payload_node(
            payload=payload,
            validate_config=rule_result["validate_config"],
            merged_concepts=rule_result["merged_concepts"],
            domains=rule_result["domains"],
            progress_callback=progress_callback,
        )
        persisted = _write_storage_and_artifacts_node(
            validated=validated,
            config=config,
            file_path=file_path,
            resume_identity=resume_identity,
            prompt_text=str(llm_result["prompt_text"]),
            raw_response=str(llm_result["raw_response"]),
            job_store=job_store,
            progress_callback=progress_callback,
        )
        job_store.mark_finished(run_id=run_id, status="SUCCEEDED", parser_mode=parser_mode, resolve_mode=resolve_mode)
        return persisted
    except Exception as error:
        job_store.mark_finished(
            run_id=run_id,
            status="FAILED",
            parser_mode=parser_mode,
            resolve_mode=resolve_mode,
            error_message=f"{type(error).__name__}: {error}",
        )
        raise


def _parse_resume_node(
    *,
    file_path: Path,
    config: Dict[str, Any],
    progress_callback: Callable[[str], None] | None,
) -> tuple[List[DocumentBlock], Dict[str, Any]]:
    _progress(progress_callback, "1/6 parse resume blocks")
    blocks, parser_diag = parse_resume_to_blocks_with_diagnostics(file_path, config)
    parser_mode = str(parser_diag.get("parser_mode", "builtin"))
    _progress(progress_callback, f"parser={parser_mode} blocks={len(blocks)}")
    return blocks, parser_diag


def _build_rule_candidates_node(
    *,
    blocks: List[DocumentBlock],
    file_path: Path,
    config: Dict[str, Any],
    progress_callback: Callable[[str], None] | None,
) -> Dict[str, Any]:
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
    return {
        "rule_payload": rule_payload,
        "validate_config": validate_config,
        "merged_concepts": merged_concepts,
        "domains": domains,
    }


def _resolve_with_llm_or_rule_fallback_node(
    *,
    rule_payload: Dict[str, Any],
    config: Dict[str, Any],
    progress_callback: Callable[[str], None] | None,
) -> Dict[str, Any]:
    project_boundary_quality = dict(rule_payload.get("project_boundary_quality", {}) or {})
    repair_required = project_boundary_quality.get("status") == "repair_required"
    prompt_text = (
        build_project_repair_prompt(rule_payload=rule_payload, config=config)
        if repair_required
        else build_resume_check_prompt(rule_payload=rule_payload, config=config)
    )
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
        raw_response = f"fallback due to: {error}"
        llm_payload = {
            **build_project_chunks_from_rule_candidates(rule_payload),
            "resolve_mode": "rule_fallback",
            "fallback_reason": f"{type(error).__name__}: {error}",
            "llm_prompt": prompt_text,
            "raw_response": raw_response,
            "project_boundary_mode": "repair_failed" if repair_required else "normal_failed",
        }
        resolve_mode = "rule_fallback"
        _progress(progress_callback, f"rule_fallback reason={type(error).__name__}")
    return {
        "llm_payload": llm_payload,
        "prompt_text": prompt_text,
        "raw_response": raw_response,
        "resolve_mode": resolve_mode,
    }


def _validate_payload_node(
    *,
    payload: Dict[str, Any],
    validate_config: ValidateConfig,
    merged_concepts: Dict[str, Dict[str, Any]],
    domains: Dict[str, Any],
    progress_callback: Callable[[str], None] | None,
) -> Dict[str, Any]:
    _progress(progress_callback, "4/6 validate result")
    return validate_resume_payload(
        payload=payload,
        validate_config=validate_config,
        allowed_concepts=set(merged_concepts.keys()),
        allowed_domains=set(domains.keys()),
    )


def _apply_storage_gate_node(*, validated: Dict[str, Any]) -> Dict[str, Any]:
    return apply_storage_quality_gate(validated)


def _write_storage_and_artifacts_node(
    *,
    validated: Dict[str, Any],
    config: Dict[str, Any],
    file_path: Path,
    resume_identity: str,
    prompt_text: str,
    raw_response: str,
    job_store: PipelineJobStore,
    progress_callback: Callable[[str], None] | None,
) -> Dict[str, Any]:
    _progress(progress_callback, "5/6 write SQL rows and Chroma vectors")
    storage_payload = _apply_storage_gate_node(validated=validated)
    evidence_chunks = [
        *_work_evidence_chunks(storage_payload.get("work_experiences", []) or []),
        *list(storage_payload.get("project_chunks", []) or []),
    ]
    chunk_vectors = build_vector_payload(
        chunk_payloads=evidence_chunks,
        config=config,
        resume_identity=resume_identity,
    )
    structured_backend = build_structured_backend(config)
    vector_backend = build_vector_backend(config)
    replaced_existing = structured_backend.upsert(storage_payload)
    vector_backend.replace_resume_chunk_vectors(resume_identity, chunk_vectors)

    persisted = {**validated}
    persisted["run_meta"] = dict(persisted.get("run_meta", {}) or {})
    persisted["run_meta"]["replaced_existing_resume"] = replaced_existing
    persisted["run_meta"]["prior_run_count"] = job_store.count_runs_for_resume(resume_identity)
    persisted["storage_gate"] = dict(storage_payload.get("storage_gate", {}) or {})
    persisted["project_count_for_storage"] = int(storage_payload.get("project_count_for_storage", 0) or 0)
    persisted["storage_summary"] = build_storage_summary(storage_payload, chunk_vectors)
    _progress(
        progress_callback,
        "storage "
        f"project_rows={len(persisted['storage_summary'].get('project_manifest_rows', []) or [])} "
        f"vector_rows={len(persisted['storage_summary'].get('vector_rows', []) or [])} "
        f"blocked={persisted['storage_gate'].get('storage_blocked_reason', '')}",
    )

    _progress(progress_callback, "6/6 write latest/history logs")
    write_run_artifacts(
        config=config,
        file_path=file_path,
        payload=persisted,
        prompt_text=prompt_text,
        raw_response=raw_response,
    )
    return persisted


def _progress(callback: Callable[[str], None] | None, message: str) -> None:
    if callback is not None:
        callback(message)


def _work_evidence_chunks(work_experiences: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    chunks: List[Dict[str, Any]] = []
    for index, item in enumerate(work_experiences, start=1):
        raw_line = str(item.get("raw_line", "") or item.get("summary_raw", "") or "").strip()
        if not raw_line:
            continue
        company = str(item.get("company_name", "") or "").strip()
        title = str(item.get("job_title_raw", "") or "").strip()
        date_range = " - ".join(part for part in [str(item.get("start_date", "") or "").strip(), str(item.get("end_date", "") or "").strip()] if part)
        work_ref = str(item.get("work_ref", "") or "").strip() or f"work_{index}"
        chunks.append(
            {
                "chunk_id": f"work_{work_ref}",
                "source_type": "work_experience",
                "project_id": work_ref,
                "project_title": company or title or work_ref,
                "project_summary": raw_line[:180],
                "chunk_text": raw_line,
                "source_section": "work_experience",
                "organization_raw": company,
                "date_range_raw": date_range,
                "title": title,
                "company": company,
                "project_tags": [],
                "confidence": float(item.get("confidence", 0.0) or 0.0),
                "evidence": dict(item.get("evidence", {}) or {}),
                "source": str(item.get("source", "") or "").strip(),
            }
        )
    return chunks


def _assemble_output(
    *,
    file_path: Path,
    run_id: str,
    resume_identity: str,
    document_hash: str,
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
            "document_hash": document_hash,
            "identity_match_source": "file_hash",
            "merged_existing_candidate": False,
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


def _resolve_candidate_identity_node(
    *,
    payload: Dict[str, Any],
    config: Dict[str, Any],
    progress_callback: Callable[[str], None] | None,
) -> Dict[str, Any]:
    resolved = {**payload}
    run_meta = dict(resolved.get("run_meta", {}) or {})
    document_hash = str(run_meta.get("document_hash", "") or run_meta.get("resume_identity", "")).strip()
    candidate_profile = dict(resolved.get("candidate_profile", {}) or {})
    match = _find_existing_candidate_identity(
        db_path=Path(config["paths"]["structured_store_file"]),
        candidate_profile=candidate_profile,
        document_hash=document_hash,
    )
    if match:
        run_meta["resume_identity"] = match["resume_identity"]
        run_meta["identity_match_source"] = match["source"]
        run_meta["merged_existing_candidate"] = match["resume_identity"] != document_hash
        _progress(progress_callback, f"identity matched by {match['source']}")
    else:
        run_meta["resume_identity"] = document_hash
        run_meta["identity_match_source"] = "file_hash"
        run_meta["merged_existing_candidate"] = False
        _progress(progress_callback, "identity matched by file_hash")
    resolved["run_meta"] = run_meta
    return resolved


def _find_existing_candidate_identity(*, db_path: Path, candidate_profile: Dict[str, Any], document_hash: str) -> Dict[str, str] | None:
    if not db_path.exists():
        return None
    contact = dict(candidate_profile.get("contact", {}) or {})
    email = _normalize_email(dict(contact.get("email", {}) or {}).get("value", ""))
    phone = _normalize_phone(dict(contact.get("phone", {}) or {}).get("value", ""))
    name = _normalize_name(dict(candidate_profile.get("name", {}) or {}).get("value", ""))
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = [dict(row) for row in conn.execute("SELECT resume_identity, email, phone, name FROM candidates").fetchall()]
    except sqlite3.Error:
        return None
    for source, value, normalizer in (
        ("email", email, lambda item: _normalize_email(item.get("email", ""))),
        ("phone", phone, lambda item: _normalize_phone(item.get("phone", ""))),
        ("name", name, lambda item: _normalize_name(item.get("name", ""))),
    ):
        if not value:
            continue
        matches = [row for row in rows if normalizer(row) == value]
        if len(matches) == 1:
            return {"resume_identity": str(matches[0].get("resume_identity", "") or document_hash), "source": source}
        if len(matches) > 1:
            return None
    return None


def _normalize_email(value: Any) -> str:
    return str(value or "").strip().lower()


def _normalize_phone(value: Any) -> str:
    digits = re.sub(r"\D+", "", str(value or ""))
    if digits.startswith("86") and len(digits) > 11:
        digits = digits[2:]
    return digits


def _normalize_name(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "").strip())


def _compute_document_hash(file_path: Path) -> str:
    data = file_path.read_bytes()
    return hashlib.sha256(data).hexdigest()


def _ensure_directories(config: Dict[str, Any]) -> None:
    for value in config.get("paths", {}).values():
        path = Path(value)
        if path.suffix:
            path.parent.mkdir(parents=True, exist_ok=True)
        else:
            path.mkdir(parents=True, exist_ok=True)
