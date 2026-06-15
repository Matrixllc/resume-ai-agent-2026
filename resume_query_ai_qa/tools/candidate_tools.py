"""Candidate listing, counting, and deterministic filters."""

from __future__ import annotations

from typing import Dict, Iterable, List

from resume_query_tools import get_candidate_profile, get_project_evidence, list_candidates
from resume_query_tools.config import get_tools_config
from resume_query_tools.stores.sql_reader import ResumeSqlReader

from resume_query_ai_qa.core.schemas import CandidateBrief

from .common import (
    brief_from_detail,
    brief_from_list_item,
    candidate_search_text,
    dedupe_terms,
    education_evidence_refs,
    education_text,
    matches_all,
    matches_any,
    normalize_domain_filter,
    normalize_key,
)


def list_all_candidates() -> List[CandidateBrief]:
    """Return every candidate as a lightweight, display-safe brief.

    这里不返回 phone/email/wechat。候选人列表类问题只需要知道“都有谁”
    和少量可筛选字段，联系方式属于更高敏感度字段，默认不进入 QA 答案。
    """
    response = list_candidates()
    return [brief_from_list_item(item) for item in response.candidates]


def filter_candidates(
    *,
    domains_any: List[str] | None = None,
    domains_all: List[str] | None = None,
    skills_all: List[str] | None = None,
    concepts_all: List[str] | None = None,
    candidate_ids: List[str] | None = None,
    domain: str | None = None,
    skills: List[str] | None = None,
    keywords: List[str] | None = None,
    education_keywords: List[str] | None = None,
    project_tags: List[str] | None = None,
    job_intent: str | None = None,
) -> List[CandidateBrief]:
    """按结构化条件做确定性候选人筛选。

    数据来源：SQLite 中的候选人表、标签表、工作/教育/项目 manifest；必要时读取
    项目证据拼搜索文本。

    参数说明：
    - domains_any/domains_all：领域并集/交集，例如 Finance。
    - skills_all/concepts_all：技能或概念必须同时满足。
    - candidate_ids：把筛选限定在上一轮候选池内。
    - keywords/education_keywords/job_intent：兼容型文本筛选。

    返回：CandidateBrief 列表，给 count/list/rank/evidence 等下游工具消费。
    边界：只筛选，不排序、不比较、不推荐、不写最终答案。
    """
    briefs = list_all_candidates()
    domains_any = dedupe_terms([*list(domains_any or []), *([domain] if domain else [])])
    domains_all = dedupe_terms(list(domains_all or []))
    skills_all = dedupe_terms([*list(skills_all or []), *list(skills or [])])
    concepts_all = dedupe_terms([*list(concepts_all or []), *list(project_tags or [])])
    domains_any = [normalize_domain_filter(item) for item in domains_any]
    domains_all = [normalize_domain_filter(item) for item in domains_all]
    if candidate_ids is not None:
        wanted = {normalize_key(item) for item in candidate_ids}
        briefs = [item for item in briefs if normalize_key(item.resume_identity) in wanted]
    tags_by_candidate = _structured_tags_by_candidate([item.resume_identity for item in briefs])

    output: List[CandidateBrief] = []
    for brief in briefs:
        tags = tags_by_candidate.get(brief.resume_identity, {})
        if domains_any and not _tag_matches_any(tags.get("domains", set()), domains_any):
            continue
        if domains_all and not _tag_matches_all(tags.get("domains", set()), domains_all):
            continue
        if skills_all and not _tag_matches_all(tags.get("skills", set()), skills_all):
            continue
        if concepts_all and not _tag_matches_all(tags.get("concepts", set()), concepts_all):
            continue
        detail = get_candidate_profile(brief.resume_identity)
        evidence = get_project_evidence(brief.resume_identity)
        haystack = candidate_search_text(detail, evidence)
        if job_intent and not matches_any(haystack, [job_intent]):
            continue
        if keywords and not matches_all(haystack, keywords):
            continue
        if education_keywords and not matches_any(education_text(detail), education_keywords):
            continue
        brief_output = brief_from_detail(detail, include_evidence=True)
        if education_keywords:
            brief_output.evidence_refs = education_evidence_refs(detail, education_keywords) + brief_output.evidence_refs
        output.append(brief_output)
    return output


def _structured_tags_by_candidate(candidate_ids: List[str]) -> Dict[str, Dict[str, set[str]]]:
    """从结构化标签库读取候选人的 domain/skill/concept 标签集合。"""
    reader = ResumeSqlReader(get_tools_config()["paths"]["structured_store_file"])
    output: Dict[str, Dict[str, set[str]]] = {}
    for row in reader.list_tags_for_candidates(candidate_ids):
        resume_identity = str(row.get("resume_identity", "") or "").strip()
        tag_type = str(row.get("tag_type", "") or "").strip()
        value = str(row.get("tag_value", "") or "").strip()
        if not resume_identity or not value:
            continue
        tags = output.setdefault(resume_identity, {"domains": set(), "skills": set(), "concepts": set()})
        if tag_type == "domain":
            tags["domains"].add(normalize_key(value))
        if tag_type == "skill":
            tags["skills"].add(normalize_key(value))
        if tag_type in {"concept", "skill", "project_tag"}:
            tags["concepts"].add(normalize_key(value))
    return output


def _tag_matches_any(actual: set[str], expected: Iterable[str]) -> bool:
    """判断实际标签是否命中任意期望标签。"""
    return any(normalize_key(value) in actual for value in expected)


def _tag_matches_all(actual: set[str], expected: Iterable[str]) -> bool:
    """判断实际标签是否覆盖全部期望标签。"""
    return all(normalize_key(value) in actual for value in expected)


def count_candidates(candidates: List[CandidateBrief] | List[str] | None = None) -> int:
    """只做人数量统计。

    如果传入 candidates，就统计这个候选池；如果不传，就统计全量候选人。
    它不负责筛选条件，因此 count/list compound 必须由 compiler 先绑定同一个
    candidate_pool，再把该 pool 传进来。
    """
    if candidates is None:
        return len(list_all_candidates())
    return len(candidates)


def get_candidate_brief(resume_identity: str) -> CandidateBrief:
    """根据简历标识返回单个候选人摘要。"""
    detail = get_candidate_profile(resume_identity)
    return brief_from_detail(detail, include_evidence=True)
