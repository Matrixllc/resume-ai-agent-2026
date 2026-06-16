"""Evidence and hybrid retrieval tools."""

from __future__ import annotations

from typing import Any, Dict, List, Literal

from resume_query_tools import get_candidate_profile, get_project_evidence
from resume_query_tools.config import get_tools_config
from resume_query_tools.stores.vector_reader import ResumeVectorReader
from resume_query_ai_qa.core.schemas import EvidenceRef

from .candidate_tools import filter_candidates, list_all_candidates
from .common import (
    match_reasons as build_match_reasons,
    matched_terms,
    matches_any,
    project_metadata_text,
    semantic_terms,
    split_terms,
    sql_profile_text,
    tag_text,
    vector_evidence_refs,
    vector_row_matches_terms,
    vector_row_score,
    vector_search_rows,
    work_text,
)
from .reference_tools import clean_retrieval_query


def get_candidate_evidence(
    resume_identity: str,
    *,
    query: str | None = None,
    limit: int = 8,
    scope: Literal["work", "project", "both"] = "both",
) -> List[EvidenceRef]:
    """返回单个候选人的经历证据引用。

    数据来源只使用 Chroma evidence chunks。scope 用于区分工作经历、项目经历或二者。
    """
    candidate_name = ""
    try:
        detail = get_candidate_profile(resume_identity)
        candidate_name = str(detail.name.value or "")
    except Exception:
        detail = None
        candidate_name = ""
    refs: List[EvidenceRef] = []
    query_terms = split_terms(clean_retrieval_query(query or ""))
    if scope in {"work", "both"}:
        refs.extend(_work_vector_refs(resume_identity, candidate_name=candidate_name, query_terms=query_terms))
    if scope in {"project", "both"}:
        refs.extend(_project_vector_refs(resume_identity, candidate_name=candidate_name, query_terms=query_terms))
    if not refs and query_terms and _is_scope_browse_query(query or ""):
        if scope in {"work", "both"}:
            refs.extend(_work_vector_refs(resume_identity, candidate_name=candidate_name, query_terms=[]))
        if scope in {"project", "both"}:
            refs.extend(_project_vector_refs(resume_identity, candidate_name=candidate_name, query_terms=[]))
    return refs[: max(limit, 0)]


def search_candidate_evidence(
    *,
    query: str,
    candidate_ids: List[str] | None = None,
    limit_per_candidate: int = 5,
    max_candidates: int | None = None,
    scope: Literal["work", "project", "both"] = "both",
) -> Dict[str, List[EvidenceRef]]:
    """为一个或多个候选人检索经历证据。

    数据来源：每个候选人的 Chroma 经历证据。

    参数：
    - query：证据检索词，通常来自 normalized_conditions/retrieval_terms。
    - candidate_ids：限定候选人范围；为空时可查全量。
    - scope：work/project/both，限定工作经历、项目经历或二者。
    - max_candidates：限制最多检查多少候选人，避免开放召回过慢。

    边界：只返回证据，不判断“谁最适合”，不生成最终中文答案。
    """
    query = clean_retrieval_query(query)
    target_ids = candidate_ids if candidate_ids is not None else [item.resume_identity for item in list_all_candidates()]
    if max_candidates is not None:
        target_ids = target_ids[: max(max_candidates, 0)]
    output: Dict[str, List[EvidenceRef]] = {}
    for resume_identity in target_ids:
        refs = get_candidate_evidence(
            resume_identity,
            query=query,
            limit=limit_per_candidate,
            scope=scope,
        )
        if not refs and not query:
            refs = get_candidate_evidence(resume_identity, limit=limit_per_candidate, scope=scope)
        output[resume_identity] = refs
    return output


def _project_vector_refs(resume_identity: str, *, candidate_name: str, query_terms: List[str]) -> List[EvidenceRef]:
    refs: List[EvidenceRef] = []
    bundle = get_project_evidence(resume_identity)
    for chunk in bundle.evidence_chunks:
        searchable = " ".join([chunk.project_title, chunk.project_summary, chunk.chunk_text, " ".join(chunk.project_tags)])
        if query_terms and not matches_any(searchable, query_terms):
            continue
        refs.append(
            EvidenceRef(
                source_type="project_experience",
                resume_identity=resume_identity,
                candidate_name=candidate_name,
                project_id=chunk.project_id,
                project_title=chunk.project_title,
                evidence_id=chunk.vector_id,
                text=chunk.chunk_text,
                strength=100,
            )
        )
    return refs


def _work_vector_refs(resume_identity: str, *, candidate_name: str, query_terms: List[str]) -> List[EvidenceRef]:
    config = get_tools_config()
    reader = ResumeVectorReader(persist_dir=config["paths"]["chroma_dir"], collection_name=config["storage"]["chroma_collection"])
    refs: List[EvidenceRef] = []
    for row in reader.list_project_chunks(resume_identity, source_type="work_experience"):
        metadata = dict(row.get("metadata", {}) or {})
        text = str(row.get("chunk_text", "") or "")
        searchable = " ".join([text, str(metadata.get("company", "") or ""), str(metadata.get("title", "") or ""), str(metadata.get("date_range_raw", "") or "")])
        if query_terms and not matches_any(searchable, query_terms):
            continue
        refs.append(
            EvidenceRef(
                source_type="work_experience",
                resume_identity=resume_identity,
                candidate_name=candidate_name,
                project_id=str(metadata.get("project_id", "") or ""),
                project_title=str(metadata.get("company", "") or metadata.get("project_title", "") or ""),
                evidence_id=str(row.get("vector_id", "") or ""),
                text=text,
                summary=str(metadata.get("project_summary", "") or ""),
                strength=100,
            )
        )
    return refs


def _is_scope_browse_query(query: str) -> bool:
    text = str(query or "")
    return any(token in text for token in ("项目经历", "项目信息", "项目经验", "工作经历", "工作信息", "工作内容", "经历")) and any(
        token in text for token in ("提出", "提取", "生成", "面试", "问题", "追问")
    )


def hybrid_search_candidates(
    *,
    query: str,
    candidate_ids: List[str] | None = None,
    top_k: int = 8,
    vector_top_k: int = 20,
) -> Dict[str, Any]:
    """通过结构化信息和向量证据做开放候选人召回。

    数据来源：
    - SQL/tag/work/project channel: 候选人画像、标签、工作经历、项目元数据；
    - vector channel: bge-m3 query embedding + Chroma project chunk search；
    - rerank: deterministic score，方便前端展示为什么召回。

    边界：这里只回答“谁相关”，不等于 JD 排序，也不产最终推荐结论。真正排序
    仍应走 score_candidates_for_jd / rank_candidates。
    """
    cleaned_query = clean_retrieval_query(query)
    query = cleaned_query or query
    terms = semantic_terms(query)
    pool = filter_candidates(candidate_ids=candidate_ids) if candidate_ids is not None else list_all_candidates()
    vector_rows, vector_warnings = vector_search_rows(query=query, candidate_ids=candidate_ids, top_k=vector_top_k)
    vector_by_candidate: Dict[str, List[Dict[str, Any]]] = {}
    for row in vector_rows:
        if terms and not vector_row_matches_terms(row, terms):
            continue
        metadata = dict(row.get("metadata", {}) or {})
        candidate_id = str(metadata.get("resume_identity", "") or "").strip()
        if candidate_id:
            vector_by_candidate.setdefault(candidate_id, []).append(row)

    recalled_by_id: Dict[str, Dict[str, Any]] = {}
    for brief in pool:
        detail = get_candidate_profile(brief.resume_identity)
        sql_hits = matched_terms(sql_profile_text(detail), terms)
        tag_hits = matched_terms(tag_text(detail), terms)
        work_hits = matched_terms(work_text(detail), terms)
        project_hits = matched_terms(project_metadata_text(detail), terms)
        vector_refs = vector_evidence_refs(
            vector_by_candidate.get(brief.resume_identity, []),
            candidate_name=str(detail.name.value or ""),
        )
        structured_hit_count = len(sql_hits) + len(tag_hits) + len(work_hits) + len(project_hits)
        vector_score = min(40.0, sum(vector_row_score(row) for row in vector_by_candidate.get(brief.resume_identity, [])[:3]))
        if structured_hit_count == 0:
            vector_score = min(vector_score, 7.0)
        score_parts = {
            "sql_profile": min(18.0, len(sql_hits) * 6.0),
            "tags": min(24.0, len(tag_hits) * 8.0),
            "work_experience": min(24.0, len(work_hits) * 8.0),
            "project_metadata": min(22.0, len(project_hits) * 7.0),
            "vector_evidence": vector_score,
        }
        total_score = sum(score_parts.values())
        if total_score <= 0:
            continue
        match_channels = [name for name, value in score_parts.items() if value > 0]
        reason_lines = build_match_reasons(
            sql_hits=sql_hits,
            tag_hits=tag_hits,
            work_hits=work_hits,
            project_hits=project_hits,
            vector_refs=vector_refs,
        )
        recalled_by_id[brief.resume_identity] = {
            "resume_identity": brief.resume_identity,
            "name": brief.name,
            "score": round(total_score, 2),
            "score_parts": {key: round(value, 2) for key, value in score_parts.items()},
            "match_reasons": reason_lines,
            "match_channels": match_channels,
            "matched_terms": sorted(set(sql_hits + tag_hits + work_hits + project_hits)),
            "vector_warnings": vector_warnings,
            "evidence_refs": [ref.model_dump() for ref in vector_refs],
        }
    recalled = list(recalled_by_id.values())
    recalled.sort(key=lambda item: (-float(item.get("score", 0.0)), str(item.get("name", ""))))
    return {"__data__": recalled[: max(top_k, 0)], "__warnings__": vector_warnings}
