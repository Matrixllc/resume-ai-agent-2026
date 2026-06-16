from __future__ import annotations

import re
from typing import Any, Dict, List, Set

from ..pipeline_yaml import ValidateConfig


def validate_resume_payload(
    *,
    payload: Dict[str, Any],
    validate_config: ValidateConfig,
    allowed_concepts: Set[str],
    allowed_domains: Set[str],
) -> Dict[str, Any]:
    candidate_profile = dict(payload.get("candidate_profile", {}) or {})
    work_experiences = list(payload.get("work_experiences", []) or [])
    education_experiences = list(payload.get("education_experiences", []) or [])
    concept_tags = _validate_tags(payload.get("concept_tags", []), allowed_concepts, validate_config.min_tag_confidence)
    domain_tags = _validate_tags(payload.get("domain_tags", []), allowed_domains, validate_config.min_tag_confidence)
    skill_tags = _validate_tags(payload.get("skill_tags", []), allowed_concepts, validate_config.min_tag_confidence)
    project_chunks, chunk_reviews = _validate_chunks(payload.get("project_chunks", []), validate_config)
    field_reviews = _validate_candidate_profile(candidate_profile, validate_config)
    validation_summary = {
        "accepted": {
            "candidate_fields": sum(1 for item in field_reviews if item["status"] == "accepted"),
            "chunks": sum(1 for item in chunk_reviews if item["status"] == "accepted"),
            "concept_tags": len(concept_tags["accepted"]),
            "domain_tags": len(domain_tags["accepted"]),
            "skill_tags": len(skill_tags["accepted"]),
        },
        "needs_review": {
            "candidate_fields": [item for item in field_reviews if item["status"] == "needs_review"],
            "chunks": [item for item in chunk_reviews if item["status"] == "needs_review"],
            "concept_tags": concept_tags["needs_review"],
            "domain_tags": domain_tags["needs_review"],
            "skill_tags": skill_tags["needs_review"],
        },
        "rejected": {
            "concept_tags": concept_tags["rejected"],
            "domain_tags": domain_tags["rejected"],
            "skill_tags": skill_tags["rejected"],
        },
    }
    return {
        **payload,
        "concept_tags": concept_tags["accepted"],
        "domain_tags": domain_tags["accepted"],
        "skill_tags": skill_tags["accepted"],
        "project_chunks": project_chunks,
        "work_experiences": work_experiences,
        "education_experiences": education_experiences,
        "validation_summary": validation_summary,
    }


def _validate_candidate_profile(profile: Dict[str, Any], config: ValidateConfig) -> List[Dict[str, Any]]:
    reviews: List[Dict[str, Any]] = []
    for key, value in profile.items():
        if key == "resume_level_skills":
            continue
        if isinstance(value, dict) and "confidence" in value:
            status = "accepted"
            if config.require_evidence and not dict(value.get("evidence", {}) or {}).get("block_ids"):
                status = "needs_review"
            if float(value.get("confidence", 0.0) or 0.0) < config.min_field_confidence:
                status = "needs_review"
            reviews.append({"field": key, "status": status, "value": value.get("value", "")})
    return reviews


def _validate_tags(items: List[Dict[str, Any]], allowed: Set[str], min_confidence: float) -> Dict[str, Any]:
    accepted: List[Dict[str, Any]] = []
    needs_review: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    for item in items:
        value = str(item.get("value", "")).strip()
        if not value:
            continue
        if allowed and value not in allowed:
            rejected.append({"value": value, "reason": "unsupported_tag"})
            continue
        if float(item.get("confidence", 0.0) or 0.0) < min_confidence:
            needs_review.append({"value": value, "reason": "low_confidence"})
            continue
        accepted.append(item)
    return {"accepted": accepted, "needs_review": needs_review, "rejected": rejected}


def _validate_chunks(items: List[Dict[str, Any]], config: ValidateConfig) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    accepted: List[Dict[str, Any]] = []
    reviews: List[Dict[str, Any]] = []
    for item in items:
        status = "accepted"
        if not str(item.get("chunk_text", "")).strip():
            continue
        if _is_non_project_chunk(item):
            reviews.append({"chunk_id": item.get("chunk_id", ""), "status": "rejected", "title": item.get("project_title", "") or item.get("chunk_title", ""), "reason": "non_project_chunk"})
            continue
        if config.require_evidence and not dict(item.get("evidence", {}) or {}).get("block_ids"):
            status = "needs_review"
        if float(item.get("confidence", 0.0) or 0.0) < config.min_chunk_confidence:
            status = "needs_review"
        reviews.append({"chunk_id": item.get("chunk_id", ""), "status": status, "title": item.get("chunk_title", "")})
        accepted.append({**item, "validation_status": status})
    return accepted, reviews


def _is_non_project_chunk(item: Dict[str, Any]) -> bool:
    title = str(item.get("project_title", "") or item.get("chunk_title", "") or "").strip()
    text = str(item.get("chunk_text", "") or "").strip()
    lines = [line.strip() for line in "\n".join([title, text]).splitlines() if line.strip()]
    if title and _is_non_project_line(title):
        return True
    return bool(lines) and all(_is_non_project_line(line) for line in lines)


def _is_non_project_line(line: str) -> bool:
    cleaned = re.sub(r"^[#\s•*-]+", "", str(line or "").strip()).strip()
    normalized = re.sub(r"\s+", "", cleaned).lower()
    if not normalized:
        return True
    prefixes = (
        "框架:", "框架：", "语言:", "语言：", "技能:", "技能：", "个人技能",
        "toefl", "gre", "ielts", "雅思", "手机", "电话", "邮箱", "微信",
        "求职意向", "作品集", "图文作品集", "自我评价", "个人总结",
    )
    if any(normalized.startswith(prefix.replace(" ", "").lower()) for prefix in prefixes):
        return True
    if re.search(r"(?<!\d)(1[3-9]\d{9})(?!\d)", cleaned):
        return True
    if re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", cleaned):
        return True
    without_date = re.sub(r"(?:19|20)\d{2}(?:[./-]?\d{1,2}){0,2}", "", cleaned)
    without_date = re.sub(r"(至今|present|current|至|到|-|–|—|~|/|\.|年|月|\s)", "", without_date, flags=re.IGNORECASE)
    return without_date == ""
