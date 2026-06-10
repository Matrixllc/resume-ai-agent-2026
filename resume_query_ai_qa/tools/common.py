from __future__ import annotations

import re
from typing import Any, Iterable, List, Dict

from resume_query_ai_qa.core.inspection.result_inspection import normalize_string_list
from resume_query_ai_qa.core.rules.condition_rules import normalize_domain
from resume_query_ai_qa.core.rules.taxonomy import expand_query_terms
from resume_query_ai_qa.core.schemas import CandidateBrief, EvidenceRef
from resume_query_tools.config import get_tools_config
from resume_query_tools.stores.vector_reader import ResumeVectorReader

MAX_PROFILE_DISPLAY_COUNT = 5


def brief_from_list_item(item: Any) -> CandidateBrief:
    """从列表条目构建候选人摘要并返回。"""
    return CandidateBrief(
        resume_identity=item.resume_identity,
        name=item.name,
        job_intent=item.job_intent,
        location_raw=item.location_raw,
        work_count=item.work_count,
        project_count=item.project_count,
    )


def brief_from_detail(detail: Any, *, include_evidence: bool = False) -> CandidateBrief:
    """从详情构建候选人摘要并返回。"""
    evidence_refs: List[EvidenceRef] = tag_evidence_refs(detail)[:8] if include_evidence else []
    return CandidateBrief(
        resume_identity=detail.resume_identity,
        name=str(detail.name.value or ""),
        job_intent=str(detail.job_intent.value or ""),
        location_raw=str(detail.location_raw.value or ""),
        skills=tag_values(detail.skills),
        domains=tag_values([tag for tag in detail.tags if tag.tag_type == "domain"]),
        work_count=len(detail.work_experiences),
        project_count=len(detail.projects),
        evidence_refs=evidence_refs,
    )


def tag_evidence_refs(detail: Any) -> List[EvidenceRef]:
    """获取标签证据引用集合并返回。"""
    refs: List[EvidenceRef] = []
    candidate_name = str(detail.name.value or "")
    for tag in detail.tags:
        if tag.tag_type == "domain":
            source_type = "domain_tags"
            strength = 70
        elif tag.tag_type in {"skill", "concept", "raw_skill"}:
            source_type = "candidate_tags"
            strength = 45
        else:
            continue
        refs.append(
            EvidenceRef(
                source_type=source_type,
                resume_identity=detail.resume_identity,
                candidate_name=candidate_name,
                evidence_id=",".join(tag.evidence_block_ids),
                text=str(tag.tag_value or tag.raw_value or ""),
                strength=strength,
            )
        )
    return refs


def candidate_search_text(detail: Any, evidence: Any) -> str:
    """获取候选人检索文本并返回。"""
    parts: List[str] = [str(detail.name.value or ""), str(detail.job_intent.value or ""), str(detail.location_raw.value or ""), str(detail.overview_raw.value or "")]
    parts.extend(tag.tag_value for tag in detail.tags)
    parts.extend(tag.raw_value for tag in detail.tags)
    for project in detail.projects:
        parts.extend([project.project_name_raw, project.organization_raw, project.role_raw])
        parts.extend(tag.tag_value for tag in project.tags)
        parts.extend(tag.raw_value for tag in project.tags)
    for chunk in evidence.evidence_chunks:
        parts.extend([chunk.project_title, chunk.project_summary, chunk.chunk_text])
        parts.extend(chunk.project_tags)
    return "\n".join(str(part) for part in parts if str(part).strip())


def education_text(detail: Any) -> str:
    """获取教育经历文本并返回。"""
    parts: List[str] = []
    for item in detail.education_experiences:
        parts.extend([getattr(item, "school_name", ""), getattr(item, "degree", ""), getattr(item, "major", ""), getattr(item, "raw_line", "")])
    return "\n".join(str(part) for part in parts if str(part).strip())


def education_evidence_refs(detail: Any, terms: Iterable[str]) -> List[EvidenceRef]:
    """获取教育经历证据引用集合并返回。"""
    refs: List[EvidenceRef] = []
    candidate_name = str(detail.name.value or "")
    for index, item in enumerate(detail.education_experiences, start=1):
        text = " ".join(str(part) for part in [getattr(item, "school_name", ""), getattr(item, "degree", ""), getattr(item, "major", ""), getattr(item, "raw_line", "")] if str(part).strip())
        if terms and not matches_any(text, terms):
            continue
        refs.append(EvidenceRef(source_type="education_experiences", resume_identity=detail.resume_identity, candidate_name=candidate_name, evidence_id=f"{detail.resume_identity}:education:{index}", text=text, strength=85))
    return refs


def work_text(detail: Any) -> str:
    """获取工作经历文本并返回。"""
    parts: List[str] = []
    for item in detail.work_experiences:
        parts.extend([getattr(item, "company_name", ""), getattr(item, "job_title_raw", ""), getattr(item, "role_raw", ""), getattr(item, "raw_line", "")])
    return "\n".join(str(part) for part in parts if str(part).strip())


def semantic_terms(query: str) -> List[str]:
    """获取语义词项集合并返回。"""
    raw_terms = split_terms(query)
    terms = [term for term in raw_terms if normalize_key(term) not in QUERY_STOPWORDS]
    terms.extend(expand_query_terms(query, types=["domain", "concept", "skill", "major"]))
    return dedupe_terms(terms or raw_terms)


def matched_terms(text: str, terms: Iterable[str]) -> List[str]:
    """从文本中提取命中的检索词并返回。"""
    normalized = normalize_key(text)
    return [str(term) for term in terms if normalize_key(term) and normalize_key(term) in normalized]


def vector_search_rows(*, query: str, candidate_ids: List[str] | None, top_k: int) -> tuple[List[Dict[str, Any]], List[str]]:
    """获取向量检索数据行集合并返回。"""
    config = get_tools_config()
    reader = ResumeVectorReader(persist_dir=config["paths"]["chroma_dir"], collection_name=config["storage"]["chroma_collection"])
    result = reader.search_project_chunks(query=query, top_k=top_k, candidate_ids=candidate_ids)
    rows = result.get("rows", []) if isinstance(result, dict) else []
    warnings = result.get("warnings", []) if isinstance(result, dict) else []
    return [row for row in rows if isinstance(row, dict)], [str(item) for item in warnings if str(item).strip()]


def vector_evidence_refs(rows: List[Dict[str, Any]], *, candidate_name: str) -> List[EvidenceRef]:
    """获取向量证据引用集合并返回。"""
    refs: List[EvidenceRef] = []
    seen: set[str] = set()
    for row in rows[:3]:
        metadata = dict(row.get("metadata", {}) or {})
        evidence_id = str(row.get("vector_id", "") or "")
        if not evidence_id or evidence_id in seen:
            continue
        seen.add(evidence_id)
        refs.append(EvidenceRef(source_type="project_evidence", resume_identity=str(metadata.get("resume_identity", "") or ""), candidate_name=candidate_name, project_id=str(metadata.get("project_id", "") or ""), project_title=str(metadata.get("project_title", "") or ""), evidence_id=evidence_id, text=str(row.get("chunk_text", "") or ""), strength=100))
    return refs


def vector_row_score(row: Dict[str, Any]) -> float:
    """获取向量数据行评分并返回。"""
    rank = int(row.get("rank", 99) or 99)
    distance = row.get("distance")
    rank_score = max(4.0, 16.0 - max(rank - 1, 0) * 2.0)
    if distance is None:
        return rank_score
    try:
        distance_score = max(0.0, 1.0 - float(distance)) * 12.0
    except (TypeError, ValueError):
        distance_score = 0.0
    return rank_score + distance_score


def vector_row_matches_terms(row: Dict[str, Any], terms: Iterable[str]) -> bool:
    """判断向量数据行是否匹配词项集合并返回布尔值。"""
    metadata = dict(row.get("metadata", {}) or {})
    searchable = " ".join([str(row.get("chunk_text", "") or ""), str(row.get("document", "") or ""), str(metadata.get("project_title", "") or ""), str(metadata.get("project_summary", "") or ""), str(metadata.get("project_tags", "") or "")])
    return bool(matched_terms(searchable, terms))


def sql_profile_text(detail: Any) -> str:
    """获取SQL候选人画像文本并返回。"""
    parts = [str(detail.name.value or ""), str(detail.job_intent.value or ""), str(detail.location_raw.value or ""), str(detail.overview_raw.value or "")]
    for item in detail.education_experiences:
        parts.extend([getattr(item, "school_name", ""), getattr(item, "degree", ""), getattr(item, "major", ""), getattr(item, "raw_line", "")])
    return "\n".join(str(part) for part in parts if str(part).strip())


def tag_text(detail: Any) -> str:
    """获取标签文本并返回。"""
    parts: List[str] = []
    tag_groups = [getattr(detail, "tags", []), getattr(detail, "skills", []), getattr(detail, "languages", []), getattr(detail, "certifications_or_scores", [])]
    for tag in [tag for group in tag_groups for tag in list(group or [])]:
        parts.extend([getattr(tag, "tag_value", ""), getattr(tag, "raw_value", "")])
    return "\n".join(str(part) for part in parts if str(part).strip())


def project_metadata_text(detail: Any) -> str:
    """获取项目元数据文本并返回。"""
    parts: List[str] = []
    for project in detail.projects:
        parts.extend([project.project_name_raw, project.organization_raw, project.role_raw])
        parts.extend(tag.tag_value for tag in project.tags)
        parts.extend(tag.raw_value for tag in project.tags)
    return "\n".join(str(part) for part in parts if str(part).strip())


def match_reasons(*, sql_hits: List[str], tag_hits: List[str], work_hits: List[str], project_hits: List[str], vector_refs: List[EvidenceRef]) -> List[str]:
    """匹配结果原因集合并返回匹配结果。"""
    reasons: List[str] = []
    if sql_hits:
        reasons.append("画像/教育信息命中：" + "、".join(dedupe_terms(sql_hits)[:5]))
    if tag_hits:
        reasons.append("技能/领域标签命中：" + "、".join(dedupe_terms(tag_hits)[:5]))
    if work_hits:
        reasons.append("工作经历命中：" + "、".join(dedupe_terms(work_hits)[:5]))
    if project_hits:
        reasons.append("项目元数据命中：" + "、".join(dedupe_terms(project_hits)[:5]))
    if vector_refs:
        titles = [ref.project_title or ref.evidence_id for ref in vector_refs if ref.project_title or ref.evidence_id]
        reasons.append("向量证据命中：" + "、".join(titles[:3]))
    return reasons


def tag_values(tags: Iterable[Any]) -> List[str]:
    """获取标签值集合并返回。"""
    values: List[str] = []
    seen = set()
    for tag in tags:
        value = str(getattr(tag, "tag_value", "") or getattr(tag, "raw_value", "") or "").strip()
        key = normalize_key(value)
        if not value or key in seen:
            continue
        seen.add(key)
        values.append(value)
    return values


def matches_all(text: str, terms: Iterable[str]) -> bool:
    """判断结果是否匹配全部并返回布尔值。"""
    normalized = normalize_key(text)
    return all(normalize_key(term) in normalized for term in terms if str(term).strip())


def matches_any(text: str, terms: Iterable[str]) -> bool:
    """判断结果是否匹配任一并返回布尔值。"""
    normalized = normalize_key(text)
    return any(normalize_key(term) in normalized for term in terms if str(term).strip())


def split_terms(text: str) -> List[str]:
    """拆分词项集合并返回。"""
    return [item for item in re.split(r"[\s,，;；/]+", text) if item.strip()]


def dedupe_terms(values: Iterable[str]) -> List[str]:
    """去重词项集合并返回。"""
    output: List[str] = []
    seen = set()
    for value in values:
        item = str(value).strip()
        key = normalize_key(item)
        if not item or key in seen:
            continue
        seen.add(key)
        output.append(item)
    return output


def dedupe_ids(values: Iterable[str]) -> List[str]:
    """去重标识集合并返回。"""
    output: List[str] = []
    seen = set()
    for value in values:
        item = str(value).strip()
        if not item or item in seen:
            continue
        seen.add(item)
        output.append(item)
    return output


def normalize_domain_filter(value: str | None) -> str | None:
    """标准化领域筛选并返回。"""
    return normalize_domain(value)


def normalize_key(value: str) -> str:
    """标准化键并返回。"""
    return re.sub(r"\s+", "", str(value or "")).lower()


def normalize_context_list(value: Any) -> List[str]:
    """标准化上下文列表并返回。"""
    return normalize_string_list(value)


QUERY_STOPWORDS = {"的", "候选人", "谁", "有", "有没有", "哪些", "相关", "背景", "经验", "经历", "项目", "能力", "适合", "岗位", "吗", "么"}
