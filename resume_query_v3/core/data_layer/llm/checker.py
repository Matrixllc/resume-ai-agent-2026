from __future__ import annotations

import re
from typing import Any, Dict, List

from ..schemas import make_scored_value
from .llm_client import extract_json_object, invoke_llm_text
from .prompts import build_project_repair_prompt, build_resume_check_prompt


def run_llm_check(rule_payload: Dict[str, Any], config: Dict[str, Any], prompt_text: str | None = None) -> Dict[str, Any]:
    prompt = prompt_text or build_resume_check_prompt(rule_payload=rule_payload, config=config)
    raw_response = invoke_llm_text(config, prompt)
    parsed = extract_json_object(raw_response)
    merged = merge_boundary_selection(rule_payload=rule_payload, llm_payload=parsed)
    merged["llm_prompt"] = prompt
    merged["raw_response"] = raw_response
    merged["resolve_mode"] = "llm_success"
    return merged


def run_llm_project_repair(rule_payload: Dict[str, Any], config: Dict[str, Any], prompt_text: str | None = None) -> Dict[str, Any]:
    prompt = prompt_text or build_project_repair_prompt(rule_payload=rule_payload, config=config)
    raw_response = invoke_llm_text(config, prompt)
    parsed = extract_json_object(raw_response)
    merged = merge_project_repair_selection(rule_payload=rule_payload, llm_payload=parsed)
    merged["llm_prompt"] = prompt
    merged["raw_response"] = raw_response
    merged["resolve_mode"] = "llm_repair_success"
    merged["project_boundary_mode"] = "repair"
    return merged


def build_project_chunks_from_rule_candidates(rule_payload: Dict[str, Any]) -> Dict[str, Any]:
    candidate_profile = dict(rule_payload.get("candidate_profile", {}) or {})
    rule_candidates = list(rule_payload.get("project_candidate_groups", []) or [])
    cleanup_config = dict(rule_payload.get("project_cleanup_config", {}) or {})
    project_chunks: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    for item in rule_candidates:
        chunk = _project_chunk_from_candidate(item, cleanup_config=cleanup_config)
        reason = _non_project_rejection_reason(project=item, chunk=chunk, rule_payload=rule_payload)
        if reason:
            rejected.append(_rejected_project_payload(item, chunk, reason))
            continue
        project_chunks.append(chunk)
    return {
        **rule_payload,
        "candidate_profile": candidate_profile,
        "project_chunks": project_chunks,
        "rejected_non_project_blocks": rejected,
    }


def merge_boundary_selection(*, rule_payload: Dict[str, Any], llm_payload: Dict[str, Any]) -> Dict[str, Any]:
    candidate_profile = dict(rule_payload.get("candidate_profile", {}) or {})
    work_experiences = list(rule_payload.get("work_experiences", []) or [])
    education_experiences = list(rule_payload.get("education_experiences", []) or [])
    selected_name_payload = llm_payload.get("selected_name", "")
    selected_name_value = ""
    selected_name_confidence = 0.9
    selected_name_evidence_ids: List[str] = []
    if isinstance(selected_name_payload, dict):
        selected_name_value = str(selected_name_payload.get("value", "")).strip()
        selected_name_confidence = float(selected_name_payload.get("confidence", 0.9) or 0.9)
        selected_name_evidence_ids = list(selected_name_payload.get("evidence_block_ids", []) or [])
    else:
        selected_name_value = str(selected_name_payload).strip()
    if selected_name_value:
        candidate_profile["name"] = make_scored_value(
            value=selected_name_value,
            confidence=selected_name_confidence,
            evidence={"block_ids": selected_name_evidence_ids, "text_snippets": [], "page_refs": []},
            source="llm_check",
        )
    _merge_basic_fields(candidate_profile=candidate_profile, llm_payload=llm_payload)
    experience_tags = _merge_experience_tags(
        rule_tags=list(rule_payload.get("experience_tags", []) or []),
        llm_tags=list(llm_payload.get("experience_tags", []) or []),
    )
    merged_work_experiences = _merge_work_experiences(
        rule_work_experiences=work_experiences,
        llm_work_experiences=list(llm_payload.get("work_experiences", []) or []),
    )
    merged_education_experiences = _merge_education_experiences(
        rule_education_experiences=education_experiences,
        llm_education_experiences=list(llm_payload.get("education_experiences", []) or []),
    )
    rule_candidates = list(rule_payload.get("project_candidate_groups", []) or [])
    cleanup_config = dict(rule_payload.get("project_cleanup_config", {}) or {})
    projects = list(llm_payload.get("projects", []) or [])
    project_groups = list(llm_payload.get("project_groups", []) or [])
    if projects:
        filtered_projects: List[Dict[str, Any]] = []
        project_chunks = []
        rejected_non_projects: List[Dict[str, Any]] = []
        for item in projects:
            chunk = _project_chunk_from_project(item, rule_candidates, cleanup_config=cleanup_config)
            rejected_reason = _non_project_rejection_reason(project=item, chunk=chunk, rule_payload=rule_payload)
            if rejected_reason:
                rejected_non_projects.append(_rejected_project_payload(item, chunk, rejected_reason))
                continue
            if not chunk or _is_role_only_project(project=item, chunk=chunk, work_experiences=merged_work_experiences):
                continue
            filtered_projects.append(
                {
                    **item,
                    "project_name_raw": str(chunk.get("project_title", "")).strip(),
                    "organization_raw": str(chunk.get("organization_raw", "") or "").strip(),
                }
            )
            project_chunks.append(chunk)
        projects = filtered_projects
    elif project_groups:
        project_chunks = []
        rejected_non_projects = []
        for item in project_groups:
            chunk = _project_chunk_from_selection(item, rule_candidates, cleanup_config=cleanup_config)
            rejected_reason = _non_project_rejection_reason(project=item, chunk=chunk, rule_payload=rule_payload)
            if rejected_reason:
                rejected_non_projects.append(_rejected_project_payload(item, chunk, rejected_reason))
                continue
            if not chunk or _is_role_only_project(project=item, chunk=chunk, work_experiences=merged_work_experiences):
                continue
            project_chunks.append(chunk)
    else:
        project_chunks = []
        rejected_non_projects = []
        for item in rule_candidates:
            chunk = _project_chunk_from_candidate(item, cleanup_config=cleanup_config)
            rejected_reason = _non_project_rejection_reason(project=item, chunk=chunk, rule_payload=rule_payload)
            if rejected_reason:
                rejected_non_projects.append(_rejected_project_payload(item, chunk, rejected_reason))
                continue
            project_chunks.append(chunk)
    project_count = len(projects) if projects else len(project_chunks)
    return {
        **rule_payload,
        "candidate_profile": candidate_profile,
        "work_experiences": merged_work_experiences,
        "education_experiences": merged_education_experiences,
        "experience_tags": experience_tags,
        "project_count": project_count,
        "projects": projects,
        "project_chunks": project_chunks,
        "rejected_non_project_blocks": rejected_non_projects,
    }


def merge_project_repair_selection(*, rule_payload: Dict[str, Any], llm_payload: Dict[str, Any]) -> Dict[str, Any]:
    candidate_profile = dict(rule_payload.get("candidate_profile", {}) or {})
    work_experiences = list(rule_payload.get("work_experiences", []) or [])
    education_experiences = list(rule_payload.get("education_experiences", []) or [])
    projects = list(llm_payload.get("projects", []) or [])
    experience_tags = _merge_experience_tags(
        rule_tags=list(rule_payload.get("experience_tags", []) or []),
        llm_tags=list(llm_payload.get("experience_tags", []) or []),
    )
    section_blocks = list(rule_payload.get("project_repair_blocks", []) or []) or list(rule_payload.get("project_section_blocks", []) or [])
    cleanup_config = dict(rule_payload.get("project_cleanup_config", {}) or {})
    repaired_projects: List[Dict[str, Any]] = []
    project_chunks: List[Dict[str, Any]] = []
    rejected_non_projects: List[Dict[str, Any]] = []
    for index, item in enumerate(projects, start=1):
        evidence_ids = _repair_evidence_ids(list(item.get("evidence_block_ids", []) or []), section_blocks)
        chunk = _project_chunk_from_repair_project(item, section_blocks, evidence_ids, index, cleanup_config=cleanup_config)
        rejected_reason = _non_project_rejection_reason(project={**item, "evidence_block_ids": evidence_ids}, chunk=chunk, rule_payload=rule_payload)
        if rejected_reason:
            rejected_non_projects.append(_rejected_project_payload(item, chunk, rejected_reason))
            continue
        if not chunk or _is_role_only_project(project=item, chunk=chunk, work_experiences=work_experiences):
            continue
        project_source_type = str(item.get("project_source_type", "") or "").strip()
        if str(item.get("parent_work_experience_ref", "") or "").strip():
            project_source_type = "work_embedded_project"
        repaired_projects.append(
            {
                **item,
                "project_name_raw": str(chunk.get("project_title", "")).strip(),
                "project_source_type": project_source_type,
                "organization_raw": str(chunk.get("organization_raw", "") or "").strip(),
                "evidence_block_ids": evidence_ids,
            }
        )
        project_chunks.append(chunk)
    return {
        **rule_payload,
        "candidate_profile": candidate_profile,
        "work_experiences": work_experiences,
        "education_experiences": education_experiences,
        "experience_tags": experience_tags,
        "project_count": len(repaired_projects) if repaired_projects else len(project_chunks),
        "projects": repaired_projects,
        "project_chunks": project_chunks,
        "rejected_non_project_blocks": rejected_non_projects,
    }


def _merge_basic_fields(*, candidate_profile: Dict[str, Any], llm_payload: Dict[str, Any]) -> None:
    contact_payload = dict(llm_payload.get("contact", {}) or {})
    contact = dict(candidate_profile.get("contact", {}) or {})
    for field_name in ("phone", "email", "wechat"):
        value = str(contact_payload.get(field_name, "")).strip()
        if value:
            contact[field_name] = make_scored_value(
                value=value,
                confidence=0.88,
                evidence={"block_ids": list(contact_payload.get("evidence_block_ids", []) or []), "text_snippets": [], "page_refs": []},
                source="llm_check",
            )
    if contact:
        candidate_profile["contact"] = contact

    job_intent_payload = dict(llm_payload.get("job_intent", {}) or {})
    if str(job_intent_payload.get("job_intent_raw", "")).strip() or list(job_intent_payload.get("target_roles", []) or []):
        candidate_profile["job_intent"] = make_scored_value(
            value=str(job_intent_payload.get("job_intent_raw", "")).strip(),
            confidence=0.86,
            evidence={"block_ids": list(job_intent_payload.get("evidence_block_ids", []) or []), "text_snippets": [], "page_refs": []},
            source="llm_check",
            extra={"target_roles": list(job_intent_payload.get("target_roles", []) or [])},
        )

    for field_name in ("location_raw", "overview_raw"):
        value = str(llm_payload.get(field_name, "")).strip()
        if value:
            candidate_profile[field_name] = make_scored_value(
                value=value,
                confidence=0.84,
                evidence={"block_ids": [], "text_snippets": [], "page_refs": []},
                source="llm_check",
            )

    resume_skills_payload = dict(llm_payload.get("resume_level_skills", {}) or {})
    raw_skills = [str(item).strip() for item in list(resume_skills_payload.get("raw", []) or []) if str(item).strip()]
    normalized_skills = [
        make_scored_value(
            value=str(item).strip(),
            confidence=0.84,
            evidence={"block_ids": list(resume_skills_payload.get("evidence_block_ids", []) or []), "text_snippets": [], "page_refs": []},
            source="llm_check",
        )
        for item in list(resume_skills_payload.get("normalized", []) or [])
        if str(item).strip()
    ]
    if raw_skills or normalized_skills:
        candidate_profile["resume_level_skills"] = {
            "raw": raw_skills,
            "normalized": normalized_skills,
        }

    for field_name in ("languages", "certifications_or_scores", "portfolio_links"):
        values = [str(item).strip() for item in list(llm_payload.get(field_name, []) or []) if str(item).strip()]
        if values:
            candidate_profile[field_name] = [
                make_scored_value(
                    value=value,
                    confidence=0.82,
                    evidence={"block_ids": [], "text_snippets": [], "page_refs": []},
                    source="llm_check",
                )
                for value in values
            ]


def _merge_work_experiences(*, rule_work_experiences: List[Dict[str, Any]], llm_work_experiences: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not llm_work_experiences:
        return rule_work_experiences
    merged: List[Dict[str, Any]] = []
    for item in llm_work_experiences:
        evidence_ids = list(item.get("evidence_block_ids", []) or [])
        merged.append(
            {
                "work_ref": str(item.get("work_ref", "")).strip(),
                "company_name": str(item.get("company_name", "")).strip(),
                "job_title_raw": str(item.get("job_title_raw", "")).strip(),
                "start_date": str(item.get("start_date", "")).strip(),
                "end_date": str(item.get("end_date", "")).strip(),
                "location": str(item.get("location", "")).strip(),
                "summary_raw": str(item.get("summary_raw", "")).strip(),
                "raw_line": str(item.get("summary_raw", "")).strip(),
                "confidence": 0.86,
                "evidence": {"block_ids": evidence_ids, "text_snippets": [], "page_refs": []},
                "source": "llm_check",
            }
        )
    return merged


def _merge_education_experiences(
    *,
    rule_education_experiences: List[Dict[str, Any]],
    llm_education_experiences: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    if not llm_education_experiences:
        return rule_education_experiences
    merged: List[Dict[str, Any]] = []
    for item in llm_education_experiences:
        evidence_ids = list(item.get("evidence_block_ids", []) or [])
        merged.append(
            {
                "school_name": str(item.get("school_name", "")).strip(),
                "degree": str(item.get("degree", "")).strip(),
                "major": str(item.get("major", "")).strip(),
                "start_date": str(item.get("start_date", "")).strip(),
                "end_date": str(item.get("end_date", "")).strip(),
                "rank_or_gpa": str(item.get("rank_or_gpa", "")).strip(),
                "raw_line": "",
                "confidence": 0.84,
                "evidence": {"block_ids": evidence_ids, "text_snippets": [], "page_refs": []},
                "source": "llm_check",
            }
        )
    return merged


def _project_chunk_from_project(
    item: Dict[str, Any],
    rule_candidates: List[Dict[str, Any]],
    *,
    cleanup_config: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    evidence_ids = list(item.get("evidence_block_ids", []) or [])
    matched_candidates = _match_candidates_by_evidence(evidence_ids, rule_candidates)
    base = dict(matched_candidates[0] if matched_candidates else {})
    chunk_text = "\n".join(str(candidate.get("chunk_text", "")).strip() for candidate in matched_candidates if str(candidate.get("chunk_text", "")).strip())
    if not chunk_text:
        chunk_text = str(base.get("chunk_text", "")).strip()
    project_title = str(item.get("project_name_raw", "")).strip() or str(base.get("chunk_title", "")).strip()
    if not project_title and not chunk_text:
        return {}
    base_title = str(base.get("chunk_title", "")).strip()
    if _is_role_like_title(project_title) and base_title and not _is_role_like_title(base_title):
        project_title = base_title
    organization_raw = _clean_project_organization_raw(
        str(item.get("organization_raw", "")).strip() or _merge_first_nonempty(matched_candidates, "organization_raw"),
        project_title=project_title,
        chunk_text=chunk_text,
    )
    date_range_raw = str(item.get("project_date_range_raw", "")).strip() or _merge_first_nonempty(matched_candidates, "date_range_raw")
    chunk_text = _clean_project_chunk_text(
        chunk_text,
        project_title=project_title,
        organization_raw=organization_raw,
        date_range_raw=date_range_raw,
        cleanup_config=dict(cleanup_config or {}),
    )
    raw_tags = [
        *list(item.get("skill_normalized", []) or []),
        *list(item.get("domain_tags", []) or []),
        *list(item.get("skill_raw", []) or []),
    ]
    return {
        "chunk_id": str(base.get("chunk_id", "")).strip() or _chunk_id_from_block_ids(evidence_ids),
        "project_title": project_title,
        "project_summary": _short_summary(chunk_text),
        "chunk_text": chunk_text,
        "source_section": str(base.get("source_section", "")).strip(),
        "organization_raw": organization_raw,
        "date_range_raw": date_range_raw,
        "project_tags": _build_project_tags(raw_tags=raw_tags, rule_candidates=matched_candidates or ([base] if base else []), confidence=0.86),
        "confidence": 0.86,
        "evidence": {
            "block_ids": evidence_ids or _merge_evidence_block_ids(matched_candidates),
            "text_snippets": [],
            "page_refs": [],
        },
        "source": "llm_check",
        "project_source_type": str(item.get("project_source_type", "")).strip(),
        "parent_work_experience_ref": str(item.get("parent_work_experience_ref", "")).strip(),
        "role_raw": str(item.get("role_raw", "")).strip(),
        "role_normalized": str(item.get("role_normalized", "")).strip(),
    }


def _project_chunk_from_selection(
    item: Dict[str, Any],
    rule_candidates: List[Dict[str, Any]],
    *,
    cleanup_config: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    evidence_ids = list(item.get("evidence_block_ids", []) or [])
    matched_candidates = _match_candidates_by_evidence(evidence_ids, rule_candidates)
    base = dict(matched_candidates[0] if matched_candidates else {})
    chunk_text = "\n".join(str(candidate.get("chunk_text", "")).strip() for candidate in matched_candidates if str(candidate.get("chunk_text", "")).strip())
    if not chunk_text:
        chunk_text = str(base.get("chunk_text", "")).strip()
    project_title = str(item.get("project_title", "")).strip() or str(base.get("chunk_title", "")).strip()
    project_summary = str(item.get("project_summary", "")).strip() or _short_summary(chunk_text)
    raw_tags = list(item.get("project_tags", []) or [])
    project_tags = _build_project_tags(
        raw_tags=raw_tags,
        rule_candidates=matched_candidates or ([base] if base else []),
        confidence=float(item.get("confidence", 0.0) or 0.0),
    )
    if not project_title and not chunk_text:
        return {}
    organization_raw = _clean_project_organization_raw(
        _merge_first_nonempty(matched_candidates, "organization_raw"),
        project_title=project_title,
        chunk_text=chunk_text,
        project_summary=project_summary,
    )
    date_range_raw = _merge_first_nonempty(matched_candidates, "date_range_raw")
    chunk_text = _clean_project_chunk_text(
        chunk_text,
        project_title=project_title,
        organization_raw=organization_raw,
        date_range_raw=date_range_raw,
        cleanup_config=dict(cleanup_config or {}),
    )
    project_summary = str(item.get("project_summary", "")).strip() or _short_summary(chunk_text)
    return {
        "chunk_id": str(base.get("chunk_id", "")).strip() or _chunk_id_from_block_ids(evidence_ids),
        "project_title": project_title,
        "project_summary": project_summary,
        "chunk_text": chunk_text,
        "source_section": str(base.get("source_section", "")).strip(),
        "organization_raw": organization_raw,
        "date_range_raw": date_range_raw,
        "project_tags": project_tags,
        "confidence": float(item.get("confidence", 0.0) or 0.0) or float(base.get("confidence", 0.0) or 0.0),
        "evidence": {
            "block_ids": evidence_ids or _merge_evidence_block_ids(matched_candidates),
            "text_snippets": [],
            "page_refs": [],
        },
        "source": "llm_check",
    }


def _project_chunk_from_repair_project(
    item: Dict[str, Any],
    section_blocks: List[Dict[str, Any]],
    evidence_ids: List[str],
    index: int,
    cleanup_config: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    block_map = {str(block.get("block_id", "") or ""): block for block in section_blocks}
    selected_blocks = [block_map[block_id] for block_id in evidence_ids if block_id in block_map]
    chunk_text = "\n".join(str(block.get("text", "") or "").strip() for block in selected_blocks if str(block.get("text", "") or "").strip())
    project_title = str(item.get("project_name_raw", "") or item.get("project_title", "") or "").strip()
    if not project_title and selected_blocks:
        project_title = str(selected_blocks[0].get("text", "") or "").strip()
    if not project_title and not chunk_text:
        return {}
    organization_raw = _clean_project_organization_raw(
        str(item.get("organization_raw", "")).strip(),
        project_title=project_title,
        chunk_text=chunk_text,
    )
    date_range_raw = str(item.get("project_date_range_raw", "") or item.get("date_range_raw", "")).strip()
    chunk_text = _clean_project_chunk_text(
        chunk_text,
        project_title=project_title,
        organization_raw=organization_raw,
        date_range_raw=date_range_raw,
        cleanup_config=dict(cleanup_config or {}),
    )
    raw_tags = [
        *list(item.get("skill_normalized", []) or []),
        *list(item.get("domain_tags", []) or []),
        *list(item.get("skill_raw", []) or []),
    ]
    return {
        "chunk_id": _chunk_id_from_block_ids(evidence_ids) if evidence_ids else f"repair_project_{index}",
        "project_title": project_title,
        "project_summary": _short_summary(chunk_text),
        "chunk_text": chunk_text,
        "source_section": "project",
        "organization_raw": organization_raw,
        "date_range_raw": date_range_raw,
        "project_tags": _build_project_tags(raw_tags=raw_tags, rule_candidates=[], confidence=0.86),
        "confidence": 0.86,
        "evidence": {"block_ids": evidence_ids, "text_snippets": [], "page_refs": []},
        "source": "llm_repair",
        "project_source_type": "work_embedded_project"
        if str(item.get("parent_work_experience_ref", "") or "").strip()
        else str(item.get("project_source_type", "")).strip(),
        "parent_work_experience_ref": str(item.get("parent_work_experience_ref", "")).strip(),
        "role_raw": str(item.get("role_raw", "")).strip(),
        "role_normalized": str(item.get("role_normalized", "")).strip(),
    }


def _project_chunk_from_candidate(item: Dict[str, Any], cleanup_config: Dict[str, Any] | None = None) -> Dict[str, Any]:
    project_title = str(item.get("chunk_title", "")).strip()
    candidate_type = str(item.get("candidate_type", "")).strip()
    organization_raw = _clean_project_organization_raw(
        str(item.get("organization_raw", "")).strip(),
        project_title=project_title,
        chunk_text=str(item.get("chunk_text", "")).strip(),
    )
    date_range_raw = str(item.get("date_range_raw", "")).strip()
    chunk_text = _clean_project_chunk_text(
        str(item.get("chunk_text", "")).strip(),
        project_title=project_title,
        organization_raw=organization_raw,
        date_range_raw=date_range_raw,
        cleanup_config=dict(cleanup_config or {}),
    )
    return {
        "chunk_id": str(item.get("chunk_id", "")).strip(),
        "project_title": project_title,
        "project_summary": _short_summary(chunk_text),
        "chunk_text": chunk_text,
        "source_section": str(item.get("source_section", "")).strip(),
        "organization_raw": organization_raw,
        "date_range_raw": date_range_raw,
        "project_tags": _build_project_tags(raw_tags=[], rule_candidates=[item], confidence=float(item.get("confidence", 0.0) or 0.0)),
        "confidence": float(item.get("confidence", 0.0) or 0.0),
        "evidence": dict(item.get("evidence", {}) or {}),
        "source": "rule_fallback",
        "candidate_type": candidate_type,
        "project_source_type": _project_source_type_from_candidate_type(candidate_type),
        "parent_work_experience_ref": str(item.get("parent_work_experience_ref", "")).strip(),
    }


def _project_source_type_from_candidate_type(candidate_type: str) -> str:
    value = str(candidate_type or "").strip()
    if value.startswith("work_embedded"):
        return "work_embedded_project"
    if value.startswith("standalone"):
        return "standalone_project"
    return value


def _non_project_rejection_reason(*, project: Dict[str, Any], chunk: Dict[str, Any], rule_payload: Dict[str, Any]) -> str:
    if not chunk:
        return "empty_project_chunk"
    title = str(
        project.get("project_name_raw", "")
        or project.get("project_title", "")
        or chunk.get("project_title", "")
        or chunk.get("chunk_title", "")
    ).strip()
    chunk_text = str(chunk.get("chunk_text", "") or "").strip()
    evidence_ids = [
        str(item).strip()
        for item in list(
            project.get("evidence_block_ids", [])
            or dict(chunk.get("evidence", {}) or {}).get("block_ids", [])
            or []
        )
        if str(item).strip()
    ]
    block_texts = _evidence_texts(rule_payload, evidence_ids)
    searchable = "\n".join([title, chunk_text, *block_texts]).strip()
    if not title and not chunk_text:
        return "empty_project"
    if _is_non_project_title(title):
        return "non_project_title"
    if evidence_ids and block_texts and all(_is_non_project_evidence_line(text) for text in block_texts):
        return "non_project_evidence_only"
    substantive_lines = [
        line
        for line in [title, *str(chunk_text or "").splitlines(), *block_texts]
        if line.strip() and not _is_non_project_evidence_line(line)
    ]
    if not substantive_lines:
        return "no_substantive_project_line"
    if _looks_like_skill_list_only(searchable):
        return "skill_list_only"
    return ""


def _evidence_texts(rule_payload: Dict[str, Any], evidence_ids: List[str]) -> List[str]:
    if not evidence_ids:
        return []
    text_by_id: Dict[str, str] = {}
    for collection_name in ("block_actions", "selected_blocks", "project_section_blocks", "project_repair_blocks"):
        for block in list(rule_payload.get(collection_name, []) or []):
            block_id = str(block.get("block_id", "") or "").strip()
            text = str(block.get("text", "") or "").strip()
            if block_id and text:
                text_by_id[block_id] = text
    return [text_by_id[block_id] for block_id in evidence_ids if block_id in text_by_id]


def _is_non_project_title(title: str) -> bool:
    cleaned = re.sub(r"^[#\s•*-]+", "", str(title or "").strip()).strip()
    normalized = re.sub(r"\s+", "", cleaned).lower()
    if not normalized:
        return False
    non_project_prefixes = (
        "框架:", "框架：", "语言:", "语言：", "技能:", "技能：", "个人技能",
        "toefl", "gre", "ielts", "雅思", "手机", "电话", "邮箱", "微信",
        "求职意向", "作品集", "图文作品集", "自我评价", "个人总结",
    )
    if any(normalized.startswith(prefix.replace(" ", "").lower()) for prefix in non_project_prefixes):
        return True
    if _is_date_only_project_line(cleaned):
        return True
    if _looks_like_contact_line(cleaned):
        return True
    return False


def _is_non_project_evidence_line(text: str) -> bool:
    cleaned = re.sub(r"^[#\s•*-]+", "", str(text or "").strip()).strip()
    if not cleaned:
        return True
    if _is_non_project_title(cleaned):
        return True
    if _is_date_only_project_line(cleaned) or _looks_like_contact_line(cleaned):
        return True
    lowered = cleaned.lower()
    if re.search(r"\b(?:toefl|gre|ielts)\b", lowered):
        return True
    if len(cleaned) <= 48 and any(token in cleaned for token in ("美国", "中国", "上海", "北京", "深圳", "广州", "休斯顿")):
        residue = re.sub(r"(美国|中国|上海|北京|深圳|广州|休斯顿|,|，|-|\s)", "", cleaned)
        if not residue:
            return True
    return False


def _looks_like_skill_list_only(text: str) -> bool:
    cleaned = str(text or "").strip()
    if not cleaned:
        return False
    lowered = cleaned.lower()
    if not re.search(r"(框架|语言|技能|java|python|sql|redis|kafka|mongodb|node\.?js|spring)", lowered, flags=re.IGNORECASE):
        return False
    action_tokens = (
        "开发", "实现", "设计", "构建", "优化", "负责", "参与", "提升",
        "developed", "implemented", "designed", "built", "optimized",
    )
    project_tokens = ("项目", "系统", "平台", "搜索", "推荐", "解析", "引擎", "应用")
    return not any(token in cleaned.lower() for token in action_tokens) and not any(token in cleaned for token in project_tokens)


def _is_date_only_project_line(text: str) -> bool:
    cleaned = str(text or "").strip()
    if not cleaned or len(cleaned) > 60:
        return False
    without_date = re.sub(r"(?:19|20)\d{2}(?:[./-]?\d{1,2}){0,2}", "", cleaned)
    without_date = re.sub(r"(至今|present|current|至|到|-|–|—|~|/|\.|年|月|\s)", "", without_date, flags=re.IGNORECASE)
    return without_date == ""


def _looks_like_contact_line(text: str) -> bool:
    cleaned = str(text or "").strip()
    if re.search(r"(?<!\d)(1[3-9]\d{9})(?!\d)", cleaned):
        return True
    if re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", cleaned):
        return True
    return bool(re.search(r"(微信|wechat|电话|手机|email|邮箱)", cleaned, flags=re.IGNORECASE))


def _rejected_project_payload(project: Dict[str, Any], chunk: Dict[str, Any], reason: str) -> Dict[str, Any]:
    return {
        "reason": reason,
        "project_name_raw": str(project.get("project_name_raw", "") or project.get("project_title", "") or chunk.get("project_title", "") or "").strip(),
        "evidence_block_ids": list(project.get("evidence_block_ids", []) or dict(chunk.get("evidence", {}) or {}).get("block_ids", []) or []),
    }


def _is_role_only_project(*, project: Dict[str, Any], chunk: Dict[str, Any], work_experiences: List[Dict[str, Any]]) -> bool:
    project_title = str(
        project.get("project_name_raw", "")
        or project.get("project_title", "")
    ).strip()
    chunk_title = str(chunk.get("project_title", "") or chunk.get("chunk_title", "")).strip()
    chunk_text = str(chunk.get("chunk_text", "") or "")
    if str(project.get("parent_work_experience_ref", "") or "").strip() and _has_substantive_project_body(chunk_text):
        return False
    if _is_role_like_title(project_title) and chunk_title and not _is_role_like_title(chunk_title):
        return False
    title = project_title or chunk_title
    if not title:
        return False
    normalized_title = _normalize_title_for_compare(title)
    for work in work_experiences:
        job_title = _normalize_title_for_compare(str(work.get("job_title_raw", "")).strip())
        company_name = _normalize_title_for_compare(str(work.get("company_name", "")).strip())
        if normalized_title and normalized_title in {job_title, company_name}:
            return True
    project_nouns = (
        "系统", "平台", "项目", "应用", "模型", "算法", "推荐", "搜索", "解析", "管理",
        "服务", "网站", "工具", "引擎", "app", "api", "pdf", "nasa", "机器学习",
    )
    role_words = (
        "开发", "工程师", "developer", "engineer", "后端", "前端", "全栈", "算法工程师",
        "软件工程师", "实习", "经理",
    )
    lowered = title.lower()
    has_project_noun = any(token in lowered for token in project_nouns)
    has_role_word = any(token in lowered for token in role_words)
    return has_role_word and not has_project_noun


def _has_substantive_project_body(text: str) -> bool:
    lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
    if len(lines) >= 4:
        return True
    bullet_lines = [
        line
        for line in lines
        if line.startswith(("-", "•", "·")) or re.match(r"^\d+[.、]\s+", line)
    ]
    return len(bullet_lines) >= 2


def _is_role_like_title(title: str) -> bool:
    lowered = str(title or "").strip().lower()
    if not lowered:
        return False
    project_nouns = (
        "系统", "平台", "项目", "应用", "模型", "算法", "推荐", "搜索", "解析", "管理",
        "服务", "网站", "工具", "引擎", "app", "api", "pdf", "nasa", "机器学习",
    )
    role_words = (
        "开发", "工程师", "developer", "engineer", "后端", "前端", "全栈", "算法工程师",
        "软件工程师", "实习", "经理",
    )
    return any(token in lowered for token in role_words) and not any(token in lowered for token in project_nouns)


def _normalize_title_for_compare(value: str) -> str:
    return re.sub(r"[\s/|,，:：;；()（）-]+", "", value).lower()


def _build_project_tags(*, raw_tags: List[Any], rule_candidates: List[Dict[str, Any]], confidence: float) -> List[Dict[str, Any]]:
    values: List[str] = []
    for tag in raw_tags:
        value = str(tag).strip()
        if value:
            values.append(value)
    if not values:
        for rule_candidate in rule_candidates:
            for tag in list(rule_candidate.get("project_tags", []) or []):
                if isinstance(tag, dict):
                    value = str(tag.get("value", "")).strip()
                    if value:
                        values.append(value)
            for tag in list(rule_candidate.get("concept_tags", []) or []):
                value = str(tag.get("value", "")).strip()
                if value:
                    values.append(value)
    evidence = {"block_ids": _merge_evidence_block_ids(rule_candidates), "text_snippets": [], "page_refs": []}
    deduped: List[Dict[str, Any]] = []
    seen = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(
            make_scored_value(
                value=value,
                confidence=confidence or _max_candidate_confidence(rule_candidates) or 0.65,
                evidence=evidence,
                source="llm_check" if raw_tags else _first_candidate_source(rule_candidates),
            )
        )
    return deduped


def _clean_project_organization_raw(
    organization_raw: str,
    *,
    project_title: str,
    chunk_text: str,
    project_summary: str = "",
) -> str:
    value = str(organization_raw or "").strip()
    if not value:
        return ""
    normalized = _normalize_title_for_compare(value)
    if not normalized:
        return ""
    title_key = _normalize_title_for_compare(project_title)
    chunk_key = _normalize_title_for_compare(chunk_text)
    summary_key = _normalize_title_for_compare(project_summary)
    if title_key and normalized == title_key:
        return ""
    if chunk_key and (normalized == chunk_key or (len(normalized) >= 24 and normalized in chunk_key)):
        return ""
    if summary_key and (normalized == summary_key or (len(normalized) >= 24 and normalized in summary_key)):
        return ""
    if _looks_like_project_body_text(value):
        return ""
    return value


def _looks_like_project_body_text(value: str) -> bool:
    cleaned = str(value or "").strip()
    if len(cleaned) <= 40:
        return False
    organization_tokens = (
        "university",
        "college",
        "school",
        "technology",
        "software",
        "marketing",
        "group",
        "corporation",
        "inc",
        "llc",
        "公司",
        "大学",
        "学院",
        "集团",
        "科技",
        "软件",
    )
    lowered = cleaned.lower()
    if len(cleaned) <= 80 and any(token in lowered or token in cleaned for token in organization_tokens):
        return False
    action_tokens = (
        "针对",
        "进行",
        "寻找",
        "帮助",
        "负责",
        "实现",
        "开发",
        "优化",
        "使用",
        "参与",
        "designed",
        "developed",
        "implemented",
        "optimized",
        "using",
    )
    punctuation_like_body = any(mark in cleaned for mark in (",", "，", "。", ";", "；"))
    has_action = any(token in lowered or token in cleaned for token in action_tokens)
    return len(cleaned) > 60 or (punctuation_like_body and has_action)


def _match_candidates_by_evidence(evidence_ids: List[str], candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    matched: List[Dict[str, Any]] = []
    target = set(evidence_ids)
    for candidate in candidates:
        candidate_ids = set(dict(candidate.get("evidence", {}) or {}).get("block_ids", []) or [])
        if target & candidate_ids:
            matched.append(candidate)
    if matched:
        return matched
    best: Dict[str, Any] = {}
    best_score = -1
    for candidate in candidates:
        candidate_ids = set(dict(candidate.get("evidence", {}) or {}).get("block_ids", []) or [])
        score = len(target & candidate_ids)
        if score > best_score:
            best_score = score
            best = candidate
    return [best] if best else []


def _repair_evidence_ids(evidence_ids: List[str], section_blocks: List[Dict[str, Any]]) -> List[str]:
    ordered_ids = [str(block.get("block_id", "") or "") for block in section_blocks if str(block.get("block_id", "") or "")]
    existing = [str(block_id).strip() for block_id in evidence_ids if str(block_id).strip() in set(ordered_ids)]
    if not existing:
        return []
    indexes = [ordered_ids.index(block_id) for block_id in existing]
    start = min(indexes)
    end = max(indexes)
    extended_end = end
    for index in range(end + 1, len(section_blocks)):
        text = str(section_blocks[index].get("text", "") or "")
        if _looks_like_repair_project_title(text):
            break
        if _is_project_internal_heading(text) or _is_numbered_detail(text):
            extended_end = index
            continue
        if index <= end + 1 and not _looks_like_repair_project_title(text):
            extended_end = index
            continue
        break
    return ordered_ids[start : extended_end + 1]


def _looks_like_repair_project_title(text: str) -> bool:
    cleaned = re.sub(r"^[#\s•*-]+", "", str(text or "").strip()).strip()
    if not cleaned or _is_project_internal_heading(cleaned):
        return False
    if len(cleaned) > 90:
        return False
    if _is_numbered_detail(cleaned):
        return False
    if str(text or "").strip().startswith("#"):
        return True
    if re.match(r"^\d+[.、]\s*(?:[•]\s*)?\S+", cleaned):
        return True
    project_tokens = ("项目", "系统", "平台", "引擎", "推荐", "搜索", "交易", "中台")
    return any(token in cleaned for token in project_tokens)


def _is_project_internal_heading(text: str) -> bool:
    normalized = re.sub(r"[\s:：#•*-]+", "", str(text or "").strip().lower())
    return normalized in {
        "项目简介",
        "项目介绍",
        "项目描述",
        "项目背景",
        "负责内容",
        "工作内容",
        "职责描述",
        "技术栈",
        "技术方案",
        "收获总结",
        "项目成果",
        "成果总结",
        "主要职责",
    }


def _is_numbered_detail(text: str) -> bool:
    cleaned = re.sub(r"^[#\s•*-]+", "", str(text or "").strip()).strip()
    matched = re.match(r"^\d+[.、]\s*(.+)", cleaned)
    if not matched:
        return False
    body = matched.group(1).strip()
    action_prefixes = (
        "实现", "开发", "负责", "参与", "完成", "搭建", "构建", "优化", "设计", "引入",
        "支持", "保证", "提升", "解决", "分析", "整理", "输出", "使用", "通过", "基于",
    )
    return body.startswith(action_prefixes) or len(body) > 36


def _merge_evidence_block_ids(candidates: List[Dict[str, Any]]) -> List[str]:
    merged: List[str] = []
    seen = set()
    for candidate in candidates:
        for block_id in list(dict(candidate.get("evidence", {}) or {}).get("block_ids", []) or []):
            if block_id and block_id not in seen:
                seen.add(block_id)
                merged.append(block_id)
    return merged


def _clean_project_chunk_text(
    text: str,
    *,
    project_title: str,
    organization_raw: str,
    date_range_raw: str,
    cleanup_config: Dict[str, Any] | None = None,
) -> str:
    lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
    output: List[str] = []
    title_key = _normalize_title_for_compare(project_title)
    organization_key = _normalize_title_for_compare(organization_raw)
    seen_metadata_boundary = False
    for index, line in enumerate(lines):
        if index == 0:
            output.append(line)
            continue
        if _is_project_stop_line(line):
            break
        if _is_project_metadata_only_line(
            line,
            title_key=title_key,
            organization_key=organization_key,
            date_range_raw=date_range_raw,
            cleanup_config=dict(cleanup_config or {}),
        ):
            seen_metadata_boundary = True
            continue
        if seen_metadata_boundary and _looks_like_numbered_next_project_boundary(line):
            break
        output.append(line)
    return "\n".join(output).strip()


def _is_project_stop_line(line: str) -> bool:
    cleaned = re.sub(r"^[#\s•*-]+", "", str(line or "").strip()).strip()
    normalized = re.sub(r"\s+", "", cleaned).lower()
    if not normalized:
        return False
    exact_or_prefix = (
        "toefl",
        "gre",
        "语言:",
        "语言：",
        "框架:",
        "框架：",
        "技能:",
        "技能：",
        "热爱生活",
        "noneedforrudecomments",
    )
    if any(normalized.startswith(token.replace(" ", "").lower()) for token in exact_or_prefix):
        return True
    return "no need for rude comments" in cleaned.lower()


def _looks_like_numbered_next_project_boundary(line: str) -> bool:
    cleaned = re.sub(r"^[#\s•*-]+", "", str(line or "").strip()).strip()
    matched = re.match(r"^\d+[.、]\s*(.+)", cleaned)
    if not matched:
        return False
    body = matched.group(1).strip()
    if not body or body.startswith("某项目"):
        return False
    lead = re.split(r"[,，;；:：。]", body, maxsplit=1)[0].strip()
    if len(lead) > 36:
        return False
    action_prefixes = (
        "实现", "开发", "负责", "参与", "完成", "搭建", "构建", "优化", "设计", "引入",
        "支持", "保证", "提升", "解决", "分析", "整理", "输出", "使用", "通过", "基于",
        "受", "将", "利用",
    )
    if lead.startswith(action_prefixes):
        return False
    boundary_tokens = (
        "识别", "检索", "搜索", "推荐", "系统", "平台", "模型", "重构", "引擎", "中台",
        "redis", "poi", "brand",
    )
    return any(token in lead.lower() for token in boundary_tokens)


def _is_project_metadata_only_line(
    line: str,
    *,
    title_key: str,
    organization_key: str,
    date_range_raw: str,
    cleanup_config: Dict[str, Any],
) -> bool:
    cleaned = str(line or "").strip()
    if not cleaned:
        return True
    normalized = _normalize_title_for_compare(cleaned)
    if normalized and normalized == title_key:
        return False
    if re.fullmatch(r"(?:19|20)\d{2}[./-]?\d{0,2}\s*(?:至|到|-|–|—|~|to)\s*(?:至今|present|current|(?:19|20)\d{2}[./-]?\d{0,2})", cleaned, flags=re.IGNORECASE):
        return True
    if date_range_raw and _normalize_title_for_compare(date_range_raw) == normalized:
        return True
    if organization_key and (normalized == organization_key or normalized in organization_key or organization_key in normalized):
        return True
    tail_tokens = _string_list_from_config(cleanup_config.get("tail_boundary_tokens"))
    if any(token in cleaned for token in tail_tokens):
        return True
    if re.search(r"(?<!\d)(1[3-9]\d{9})(?!\d)", cleaned) or re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", cleaned):
        return True
    action_tokens = _string_list_from_config(cleanup_config.get("metadata_action_keep_tokens"))
    if any(token in cleaned for token in action_tokens):
        return False
    org_regex = str(cleanup_config.get("metadata_org_regex", "") or "").strip()
    if org_regex and re.search(org_regex, cleaned, flags=re.IGNORECASE):
        return True
    location_tokens = _string_list_from_config(cleanup_config.get("metadata_location_tokens"))
    max_line_length = int(cleanup_config.get("metadata_max_line_length", 40) or 40)
    if any(token in cleaned for token in location_tokens) and len(cleaned) <= max_line_length:
        return True
    return False


def _string_list_from_config(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _dedupe_experience_tags(tags: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    output: List[Dict[str, Any]] = []
    seen = set()
    for tag in sorted(tags, key=lambda item: float(item.get("confidence", 0.0) or 0.0), reverse=True):
        value = str(tag.get("value", "") or "").strip()
        key = re.sub(r"\s+", "", value).lower()
        if not key or key in seen:
            continue
        seen.add(key)
        output.append(tag)
    return output


def _merge_experience_tags(*, rule_tags: List[Dict[str, Any]], llm_tags: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    normalized_llm_tags: List[Dict[str, Any]] = []
    for item in llm_tags:
        value = str(item.get("tag_value", "") or item.get("value", "") or "").strip()
        if not value:
            continue
        confidence = min(max(float(item.get("confidence", 0.0) or 0.0), 0.0), 0.82)
        if confidence < 0.55:
            continue
        normalized_llm_tags.append(
            make_scored_value(
                value=value,
                confidence=confidence,
                evidence={"block_ids": list(item.get("evidence_block_ids", []) or []), "text_snippets": [], "page_refs": []},
                source="llm_experience_estimate",
                extra={"reason": str(item.get("reason", "") or "").strip()},
            )
        )
    if not rule_tags:
        return _dedupe_experience_tags(normalized_llm_tags)
    max_rule_confidence = max(float(item.get("confidence", 0.0) or 0.0) for item in rule_tags)
    if max_rule_confidence >= 0.8:
        return _dedupe_experience_tags(rule_tags)
    return _dedupe_experience_tags([*rule_tags, *normalized_llm_tags])


def _merge_first_nonempty(candidates: List[Dict[str, Any]], field_name: str) -> str:
    for candidate in candidates:
        value = str(candidate.get(field_name, "")).strip()
        if value:
            return value
    return ""


def _max_candidate_confidence(candidates: List[Dict[str, Any]]) -> float:
    if not candidates:
        return 0.0
    return max(float(candidate.get("confidence", 0.0) or 0.0) for candidate in candidates)


def _first_candidate_source(candidates: List[Dict[str, Any]]) -> str:
    for candidate in candidates:
        value = str(candidate.get("source", "")).strip()
        if value:
            return value
    return "rule"


def _short_summary(text: str) -> str:
    normalized = re.sub(r"\s+", " ", text).strip()
    return normalized[:180]


def _chunk_id_from_block_ids(block_ids: List[str]) -> str:
    if not block_ids:
        return "project_chunk_unknown"
    return "project_" + "_".join(block_ids[:3]).replace("-", "_")
