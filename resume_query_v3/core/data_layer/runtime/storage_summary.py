from __future__ import annotations

from typing import Any, Dict, List


def build_storage_summary(payload: Dict[str, Any], chunk_vectors: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Build a readable view of the exact rows prepared for SQL and vector stores."""
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
    tag_rows = _candidate_tag_rows(payload, candidate_profile)
    project_manifest_rows = _project_manifest_rows(payload)
    project_tag_rows = _project_tag_rows(payload)
    vector_rows = _vector_rows(chunk_vectors)
    return {
        "candidate_row": candidate_row,
        "work_rows": work_rows,
        "education_rows": education_rows,
        "tag_rows": tag_rows,
        "project_manifest_rows": project_manifest_rows,
        "project_tag_rows": project_tag_rows,
        "project_chunks_prepared_count": len(chunk_vectors),
        "evidence_chunks_prepared_count": len(chunk_vectors),
        "vector_rows_skipped_no_embedding": len(chunk_vectors) - len(vector_rows),
        "vector_rows": vector_rows,
    }


def _candidate_tag_rows(payload: Dict[str, Any], candidate_profile: Dict[str, Any]) -> List[Dict[str, Any]]:
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
    return _dedupe_tag_rows(tag_rows)


def _project_manifest_rows(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
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
    if project_manifest_rows:
        return project_manifest_rows
    return [
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


def _project_tag_rows(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    project_tag_rows: List[Dict[str, Any]] = []
    for index, row in enumerate(list(payload.get("projects", []) or []), start=1):
        project_id = f"project_{index}"
        for value in list(row.get("skill_normalized", []) or []):
            project_tag_rows.append({"project_id": project_id, "tag_type": "skill", "tag_value": value, "source": "llm_check"})
        for value in list(row.get("domain_tags", []) or []):
            project_tag_rows.append({"project_id": project_id, "tag_type": "domain", "tag_value": value, "source": "llm_check"})
        if row.get("role_normalized"):
            project_tag_rows.append({"project_id": project_id, "tag_type": "role", "tag_value": row.get("role_normalized", ""), "source": "llm_check"})
    return project_tag_rows


def _vector_rows(chunk_vectors: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    vector_rows = []
    for row in chunk_vectors:
        embedding_dim = len(list(row.get("embedding", []) or []))
        if embedding_dim <= 0:
            continue
        vector_rows.append(
            {
                "chunk_id": row.get("chunk_id", ""),
                "vector_id": row.get("vector_id", ""),
                "source_type": row.get("source_type", "project_experience"),
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
    return vector_rows


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
