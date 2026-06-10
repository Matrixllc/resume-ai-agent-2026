"""Profile material tools."""

from __future__ import annotations

from typing import Any, Dict, List

from resume_query_tools import get_candidate_profile

from .candidate_tools import list_all_candidates
from .common import MAX_PROFILE_DISPLAY_COUNT, dedupe_ids, tag_values
from .evidence_tools import get_candidate_evidence


def get_candidate_profile_intro(
    resume_identity: str,
    *,
    include_contact: bool = False,
) -> Dict[str, Any]:
    """返回单个候选人的画像素材。

    数据来源：SQLite 候选人详情、工作/教育/项目 manifest，加 Chroma 项目证据
    摘要。默认隐藏联系方式，只有明确 include_contact 才返回 contact。

    返回给 aggregator 的是事实素材，不包含“是否更强”“是否推荐”等评价结论。
    """
    detail = get_candidate_profile(resume_identity)
    evidence_refs = get_candidate_evidence(resume_identity)
    payload: Dict[str, Any] = {
        "resume_identity": resume_identity,
        "name": str(detail.name.value or ""),
        "job_intent": str(detail.job_intent.value or ""),
        "location_raw": str(detail.location_raw.value or ""),
        "education_experiences": [item.model_dump() for item in detail.education_experiences],
        "work_experiences": [item.model_dump() for item in detail.work_experiences],
        "skills": tag_values(detail.skills),
        "domains": tag_values([tag for tag in detail.tags if tag.tag_type == "domain"]),
        "projects": [
            {
                "project_id": item.project_id,
                "project_name_raw": item.project_name_raw,
                "organization_raw": item.organization_raw,
                "date_range_raw": item.date_range_raw,
                "tags": tag_values(item.tags),
            }
            for item in detail.projects
        ],
        "evidence_refs": [item.model_dump() for item in evidence_refs[:5]],
        "contact_hidden": not include_contact,
    }
    if include_contact:
        payload["contact"] = {
            key: str(value.value or "")
            for key, value in detail.contact.items()
            if str(value.value or "").strip()
        }
    return payload


def get_candidate_profiles_intro(
    candidate_ids: List[str],
    *,
    include_contact: bool = False,
) -> Dict[str, Any]:
    """批量返回候选人画像素材，最多展示五人。

    这个限制是展示边界：画像是高信息密度答案，一次展示过多会影响可读性，也会
    增加 answer_validator 的事实检查压力。
    """
    ids = dedupe_ids([str(item) for item in candidate_ids if str(item).strip()])
    names = _candidate_names_for_ids(ids)
    if len(ids) > MAX_PROFILE_DISPLAY_COUNT:
        return {
            "__business_error__": True,
            "__error__": "profile_display_limit_exceeded",
            "__data__": {
                "error_code": "profile_display_limit_exceeded",
                "limit": MAX_PROFILE_DISPLAY_COUNT,
                "requested_count": len(ids),
                "candidate_ids": ids,
                "candidate_names": names,
                "user_message": f"一次最多展示 {MAX_PROFILE_DISPLAY_COUNT} 位候选人的个人信息，请缩小范围或改为候选人列表。",
            },
        }
    return {
        "limit": MAX_PROFILE_DISPLAY_COUNT,
        "requested_count": len(ids),
        "profiles": [
            get_candidate_profile_intro(candidate_id, include_contact=include_contact)
            for candidate_id in ids
        ],
    }


def _candidate_names_for_ids(candidate_ids: List[str]) -> List[str]:
    """根据标识集合生成候选人名称集合并返回。"""
    id_set = set(candidate_ids)
    output: List[str] = []
    for item in list_all_candidates():
        if item.resume_identity in id_set:
            output.append(item.name or item.resume_identity)
    return output
