"""Evidence and hybrid retrieval tools."""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Literal

from resume_query_tools import get_candidate_profile, get_project_evidence
from resume_query_tools.config import get_tools_config
from resume_query_tools.stores.vector_reader import ResumeVectorReader
from resume_query_ai_qa.core.rules.taxonomy import expand_query_terms
from resume_query_ai_qa.core.schemas import EvidenceRef

from .candidate_tools import filter_candidates, list_all_candidates
from .common import (
    match_reasons as build_match_reasons,
    matched_terms,
    matches_any,
    normalize_key,
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
    work_refs: List[EvidenceRef] = []
    project_refs: List[EvidenceRef] = []
    query_terms = split_terms(clean_retrieval_query(query or ""))
    if scope in {"work", "both"}:
        work_refs = _work_vector_refs(
            resume_identity, candidate_name=candidate_name, query_terms=query_terms
        )
    if scope in {"project", "both"}:
        project_refs = _project_vector_refs(
            resume_identity, candidate_name=candidate_name, query_terms=query_terms
        )
    refs = _merge_scope_refs(work_refs, project_refs, scope=scope, limit=max(limit, 0))
    if not refs and query_terms and _is_scope_browse_query(query or ""):
        if scope in {"work", "both"}:
            work_refs = _work_vector_refs(
                resume_identity, candidate_name=candidate_name, query_terms=[]
            )
        if scope in {"project", "both"}:
            project_refs = _project_vector_refs(
                resume_identity, candidate_name=candidate_name, query_terms=[]
            )
        refs = _merge_scope_refs(work_refs, project_refs, scope=scope, limit=max(limit, 0))
    return refs


def _merge_scope_refs(
    work_refs: List[EvidenceRef],
    project_refs: List[EvidenceRef],
    *,
    scope: Literal["work", "project", "both"],
    limit: int,
) -> List[EvidenceRef]:
    """按 scope 合并经历；both 使用轮询交错，单类不足时由另一类补满。"""
    if limit <= 0:
        return []
    if scope == "work":
        return work_refs[:limit]
    if scope == "project":
        return project_refs[:limit]
    refs: List[EvidenceRef] = []
    for index in range(max(len(work_refs), len(project_refs))):
        if index < len(work_refs):
            refs.append(work_refs[index])
        if index < len(project_refs):
            refs.append(project_refs[index])
        if len(refs) >= limit:
            break
    return refs[:limit]


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
    target_ids = (
        candidate_ids
        if candidate_ids is not None
        else [item.resume_identity for item in list_all_candidates()]
    )
    if max_candidates is not None:
        target_ids = target_ids[: max(max_candidates, 0)]
    target_ids = [str(item).strip() for item in target_ids if str(item).strip()]
    output: Dict[str, List[EvidenceRef]] = {}

    # 空查询是显式的“浏览全部经历”合同，继续复用原路径，保留 work/project
    # 的既有展示顺序，且不触发 embedding。
    if not query:
        for resume_identity in target_ids:
            output[resume_identity] = get_candidate_evidence(
                resume_identity,
                limit=limit_per_candidate,
                scope=scope,
            )
        return output

    candidate_names = _candidate_names(target_ids)
    query_terms = _evidence_query_terms(query, candidate_names=candidate_names.values())
    literal_by_candidate: Dict[str, List[EvidenceRef]] = {}
    for resume_identity in target_ids:
        refs = _literal_evidence_refs(
            resume_identity,
            candidate_name=candidate_names.get(resume_identity, ""),
            query_terms=query_terms,
            scope=scope,
        )
        literal_by_candidate[resume_identity] = refs

    vector_by_candidate: Dict[str, List[tuple[float, EvidenceRef]]] = {}
    safe_limit = max(int(limit_per_candidate or 0), 0)
    needs_vector = (
        bool(query_terms)
        and safe_limit > 0
        and any(
            len(literal_by_candidate.get(candidate_id, [])) < safe_limit
            for candidate_id in target_ids
        )
    )
    if needs_vector:
        source_types = _source_types_for_scope(scope)
        try:
            vector_rows, _warnings = vector_search_rows(
                query=" ".join(query_terms),
                candidate_ids=target_ids,
                top_k=max(len(target_ids) * safe_limit * 4, 20),
                source_types=source_types,
            )
        except Exception:
            vector_rows = []
        allowed_ids = set(target_ids)
        for row in vector_rows:
            metadata = dict(row.get("metadata", {}) or {})
            resume_identity = str(metadata.get("resume_identity", "") or "").strip()
            source_type = str(metadata.get("source_type", "") or "project_experience")
            distance = _vector_distance(row)
            invalid_candidate = resume_identity not in allowed_ids
            invalid_source = source_type not in source_types
            invalid_distance = (
                distance is None or distance > EVIDENCE_VECTOR_MAX_DISTANCE
            )
            if invalid_candidate or invalid_source or invalid_distance:
                continue
            ref = _vector_row_to_evidence_ref(
                row,
                resume_identity=resume_identity,
                candidate_name=candidate_names.get(resume_identity, ""),
            )
            vector_by_candidate.setdefault(resume_identity, []).append((distance, ref))

    for resume_identity in target_ids:
        output[resume_identity] = _merge_evidence_refs(
            literal_by_candidate.get(resume_identity, []),
            vector_by_candidate.get(resume_identity, []),
            limit=safe_limit,
        )
    return output


EVIDENCE_VECTOR_MAX_DISTANCE = 0.8

_EVIDENCE_CONNECTOR_RE = re.compile(r"(?:以及|并且|或者|方面|和|与|或|及)")
_EVIDENCE_NOISE_RE = re.compile(
    r"(?:有没有|是否有|是否|有无|负责过?|参与过?|从事过?|做过|具备|拥有|"
    r"相关经历|相关经验|工作经历|项目经历|经历|经验|相关|候选人|请问|帮我|帮忙|"
    r"哪些|什么|怎么|如何|哪里|体现|介绍|说明|查找|查询|检索|找出|看下|看一下|吗|么)"
)


def _evidence_query_terms(
    query: str, *, candidate_names: Iterable[str] = ()
) -> List[str]:
    """把自然语言证据问题转换为适合字面召回的短词项。"""
    text = str(query or "").strip()
    for name in sorted(
        (str(item).strip() for item in candidate_names), key=len, reverse=True
    ):
        if name:
            text = re.sub(re.escape(name), " ", text, flags=re.IGNORECASE)
    text = _EVIDENCE_NOISE_RE.sub(" ", text)
    raw_terms = [
        item.strip(" 的地得了着过、，。；;：:!?！？()（）[]【】\"'")
        for item in re.split(r"[\s,，;；/、]+", _EVIDENCE_CONNECTOR_RE.sub(" ", text))
    ]
    raw_terms = [item for item in raw_terms if _is_meaningful_evidence_term(item)]
    expanded = expand_query_terms(
        " ".join(raw_terms), types=["domain", "skill", "concept"]
    )
    return _dedupe_evidence_terms([*raw_terms, *expanded])


def _is_meaningful_evidence_term(term: str) -> bool:
    item = str(term or "").strip()
    if not item:
        return False
    compact = normalize_key(item)
    if compact in {"有", "无", "做", "参与", "负责", "方面", "内容", "情况"}:
        return False
    if re.fullmatch(r"[A-Za-z0-9+#.\-]+", item):
        return len(compact) >= 2
    return len(compact) >= 2


def _dedupe_evidence_terms(terms: Iterable[str]) -> List[str]:
    output: List[str] = []
    seen: set[str] = set()
    for term in terms:
        item = str(term or "").strip()
        key = normalize_key(item)
        if not _is_meaningful_evidence_term(item) or key in seen:
            continue
        seen.add(key)
        output.append(item)
    return output


def _candidate_names(candidate_ids: List[str]) -> Dict[str, str]:
    names: Dict[str, str] = {}
    for candidate_id in candidate_ids:
        try:
            detail = get_candidate_profile(candidate_id)
            names[candidate_id] = str(detail.name.value or "")
        except Exception:
            names[candidate_id] = ""
    return names


def _literal_evidence_refs(
    resume_identity: str,
    *,
    candidate_name: str,
    query_terms: List[str],
    scope: Literal["work", "project", "both"],
) -> List[EvidenceRef]:
    scored: List[tuple[int, int, EvidenceRef]] = []
    ordinal = 0
    if scope in {"work", "both"}:
        for ref in _work_vector_refs(
            resume_identity, candidate_name=candidate_name, query_terms=[]
        ):
            hit_count = len(
                matched_terms(_evidence_ref_searchable_text(ref), query_terms)
            )
            if hit_count:
                scored.append((hit_count, ordinal, ref))
            ordinal += 1
    if scope in {"project", "both"}:
        for ref in _project_vector_refs(
            resume_identity, candidate_name=candidate_name, query_terms=[]
        ):
            hit_count = len(
                matched_terms(_evidence_ref_searchable_text(ref), query_terms)
            )
            if hit_count:
                scored.append((hit_count, ordinal, ref))
            ordinal += 1
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [item[2] for item in scored]


def _evidence_ref_searchable_text(ref: EvidenceRef) -> str:
    return " ".join([ref.project_title, ref.summary, ref.text])


def _source_types_for_scope(scope: Literal["work", "project", "both"]) -> List[str]:
    if scope == "work":
        return ["work_experience"]
    if scope == "project":
        return ["project_experience"]
    return ["work_experience", "project_experience"]


def _vector_distance(row: Dict[str, Any]) -> float | None:
    try:
        value = row.get("distance")
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _vector_row_to_evidence_ref(
    row: Dict[str, Any],
    *,
    resume_identity: str,
    candidate_name: str,
) -> EvidenceRef:
    metadata = dict(row.get("metadata", {}) or {})
    source_type = str(metadata.get("source_type", "") or "project_experience")
    return EvidenceRef(
        source_type=(
            source_type
            if source_type in {"work_experience", "project_experience"}
            else "project_experience"
        ),
        resume_identity=resume_identity,
        candidate_name=candidate_name,
        project_id=str(metadata.get("project_id", "") or ""),
        project_title=str(
            metadata.get("company", "") or metadata.get("project_title", "") or ""
        ),
        evidence_id=str(row.get("vector_id", "") or ""),
        text=str(row.get("chunk_text", "") or ""),
        summary=str(metadata.get("project_summary", "") or ""),
        strength=100,
    )


def _merge_evidence_refs(
    literal_refs: List[EvidenceRef],
    vector_refs: List[tuple[float, EvidenceRef]],
    *,
    limit: int,
) -> List[EvidenceRef]:
    if limit <= 0:
        return []
    output: List[EvidenceRef] = []
    seen: set[str] = set()
    ordered = [
        *literal_refs,
        *(ref for _distance, ref in sorted(vector_refs, key=lambda item: item[0])),
    ]
    for ref in ordered:
        key = ref.evidence_id or "|".join(
            [
                ref.source_type,
                ref.resume_identity,
                ref.project_id,
                normalize_key(ref.text),
            ]
        )
        if key in seen:
            continue
        seen.add(key)
        output.append(ref)
        if len(output) >= limit:
            break
    return output


def _project_vector_refs(
    resume_identity: str, *, candidate_name: str, query_terms: List[str]
) -> List[EvidenceRef]:
    refs: List[EvidenceRef] = []
    bundle = get_project_evidence(resume_identity)
    for chunk in bundle.evidence_chunks:
        searchable = " ".join(
            [
                chunk.project_title,
                chunk.project_summary,
                chunk.chunk_text,
                " ".join(chunk.project_tags),
            ]
        )
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


def _work_vector_refs(
    resume_identity: str, *, candidate_name: str, query_terms: List[str]
) -> List[EvidenceRef]:
    config = get_tools_config()
    reader = ResumeVectorReader(
        persist_dir=config["paths"]["chroma_dir"],
        collection_name=config["storage"]["chroma_collection"],
    )
    refs: List[EvidenceRef] = []
    for row in reader.list_project_chunks(
        resume_identity, source_type="work_experience"
    ):
        metadata = dict(row.get("metadata", {}) or {})
        text = str(row.get("chunk_text", "") or "")
        searchable = " ".join(
            [
                text,
                str(metadata.get("company", "") or ""),
                str(metadata.get("title", "") or ""),
                str(metadata.get("date_range_raw", "") or ""),
            ]
        )
        if query_terms and not matches_any(searchable, query_terms):
            continue
        refs.append(
            EvidenceRef(
                source_type="work_experience",
                resume_identity=resume_identity,
                candidate_name=candidate_name,
                project_id=str(metadata.get("project_id", "") or ""),
                project_title=str(
                    metadata.get("company", "")
                    or metadata.get("project_title", "")
                    or ""
                ),
                evidence_id=str(row.get("vector_id", "") or ""),
                text=text,
                summary=str(metadata.get("project_summary", "") or ""),
                strength=100,
            )
        )
    return refs


def _is_scope_browse_query(query: str) -> bool:
    text = str(query or "")
    return any(
        token in text
        for token in (
            "项目经历",
            "项目信息",
            "项目经验",
            "工作经历",
            "工作信息",
            "工作内容",
            "经历",
        )
    ) and any(token in text for token in ("提出", "提取", "生成", "面试", "问题", "追问"))


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
    pool = (
        filter_candidates(candidate_ids=candidate_ids)
        if candidate_ids is not None
        else list_all_candidates()
    )
    vector_rows, vector_warnings = vector_search_rows(
        query=query, candidate_ids=candidate_ids, top_k=vector_top_k
    )
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
        structured_hit_count = (
            len(sql_hits) + len(tag_hits) + len(work_hits) + len(project_hits)
        )
        vector_score = min(
            40.0,
            sum(
                vector_row_score(row)
                for row in vector_by_candidate.get(brief.resume_identity, [])[:3]
            ),
        )
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
            "matched_terms": sorted(
                set(sql_hits + tag_hits + work_hits + project_hits)
            ),
            "vector_warnings": vector_warnings,
            "evidence_refs": [ref.model_dump() for ref in vector_refs],
        }
    recalled = list(recalled_by_id.values())
    recalled.sort(
        key=lambda item: (-float(item.get("score", 0.0)), str(item.get("name", "")))
    )
    return {"__data__": recalled[: max(top_k, 0)], "__warnings__": vector_warnings}
