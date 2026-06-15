from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple


def apply_storage_quality_gate(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Decide which project facts are accurate enough for durable storage."""
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
