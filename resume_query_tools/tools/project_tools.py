from __future__ import annotations

import re

from ..schemas import ClassifiedProjectsResponse, DisplayClassifiedProjectsResponse, DisplayEvidenceChunk, DisplayProject
from .candidate_profile_tool import _display_tags, get_candidate_profile, get_candidate_profile_display
from .project_evidence_tool import get_project_evidence
from resume_query_v3.core.data_layer.llm.checker import _clean_project_organization_raw


def get_classified_projects(resume_identity: str) -> ClassifiedProjectsResponse:
    """读取并分类候选人项目。

    数据来源是 SQLite project manifest 和 Chroma evidence。这里只把普通项目和
    work_embedded_project 分开，供前端展示；不重新切项目边界，也不从日志补项目。
    """
    candidate = get_candidate_profile(resume_identity)
    evidence = get_project_evidence(resume_identity)
    projects = _dedupe_projects(candidate.projects)
    ordinary_projects = [
        item
        for item in projects
        if item.project_source_type != "work_embedded_project"
    ]
    work_embedded_projects = [
        item
        for item in projects
        if item.project_source_type == "work_embedded_project"
    ]
    return ClassifiedProjectsResponse(
        resume_identity=resume_identity,
        ordinary_projects=ordinary_projects,
        work_embedded_projects=work_embedded_projects,
        work_experiences=candidate.work_experiences,
        evidence_chunks=evidence.evidence_chunks,
    )


def get_classified_projects_display(resume_identity: str) -> DisplayClassifiedProjectsResponse:
    """返回前端展示用项目 DTO。

    它把项目 manifest 与 evidence chunks 对齐，做展示字段清理。边界是只整理
    已入库事实，不修复 ingestion 阶段的项目边界。
    """
    full = get_classified_projects(resume_identity)
    candidate = get_candidate_profile_display(resume_identity)
    evidence_by_id = {item.project_id: item for item in full.evidence_chunks if item.project_id}
    evidence_by_title = {item.project_title: item for item in full.evidence_chunks if item.project_title}
    display_chunks = [
        DisplayEvidenceChunk(
            project_id=item.project_id,
            project_title=item.project_title,
            source_type=item.source_type,
            evidence_origin=item.evidence_origin or "chroma",
            vector_id=item.vector_id,
            project_summary=item.project_summary,
            chunk_text=item.chunk_text,
            organization_raw=item.organization_raw,
            date_range_raw=item.date_range_raw,
            project_tags=item.project_tags,
        )
        for item in full.evidence_chunks
    ]
    covered_keys = {(item.project_id, item.project_title) for item in full.evidence_chunks}
    for project in [*full.ordinary_projects, *full.work_embedded_projects]:
        if (project.project_id, project.project_name_raw) in covered_keys:
            continue
        display_chunks.append(_fallback_project_chunk(project))
    return DisplayClassifiedProjectsResponse(
        resume_identity=resume_identity,
        ordinary_projects=[_display_project(item, evidence_by_id=evidence_by_id, evidence_by_title=evidence_by_title) for item in full.ordinary_projects],
        work_embedded_projects=[_display_project(item, evidence_by_id=evidence_by_id, evidence_by_title=evidence_by_title) for item in full.work_embedded_projects],
        work_experiences=candidate.work_experiences,
        evidence_chunks=display_chunks,
    )


def _dedupe_projects(projects):
    seen = set()
    output = []
    for project in projects:
        if not _is_displayable_project(project):
            continue
        key = _project_key(project)
        if key in seen:
            continue
        seen.add(key)
        output.append(project)
    return output


def _is_displayable_project(project) -> bool:
    source = str(getattr(project, "source", "") or "")
    source_type = str(getattr(project, "project_source_type", "") or "")
    if source == "rule_fallback" and not source_type:
        return False
    return True


def _project_key(project) -> str:
    title = _normalize_key(getattr(project, "project_name_raw", ""))
    org = _normalize_key(getattr(project, "organization_raw", ""))
    date_range = _normalize_key(getattr(project, "date_range_raw", ""))
    role = _normalize_key(getattr(project, "role_raw", "") or getattr(project, "role_normalized", ""))
    return "|".join([title, org, date_range, role])


def _normalize_key(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "")).lower()


def _display_project(project, *, evidence_by_id=None, evidence_by_title=None) -> DisplayProject:
    evidence_by_id = evidence_by_id or {}
    evidence_by_title = evidence_by_title or {}
    evidence = evidence_by_id.get(project.project_id) or evidence_by_title.get(project.project_name_raw)
    organization_raw = project.organization_raw
    if evidence:
        organization_raw = _clean_project_organization_raw(
            organization_raw,
            project_title=project.project_name_raw,
            chunk_text=evidence.chunk_text,
            project_summary=evidence.project_summary,
        )
    return DisplayProject(
        project_id=project.project_id,
        project_name_raw=project.project_name_raw,
        project_source_type=project.project_source_type,
        parent_work_experience_ref=project.parent_work_experience_ref,
        organization_raw=organization_raw,
        date_range_raw=project.date_range_raw,
        role_raw=project.role_raw,
        role_normalized=project.role_normalized,
        tags=_display_tags(project.tags),
    )


def _fallback_project_chunk(project) -> DisplayEvidenceChunk:
    tags = [tag.tag_value for tag in project.tags if tag.tag_value]
    details = [
        part
        for part in [
            project.organization_raw,
            project.date_range_raw,
            project.role_raw or project.role_normalized,
            "、".join(tags[:8]),
        ]
        if part
    ]
    return DisplayEvidenceChunk(
        project_id=project.project_id,
        project_title=project.project_name_raw,
        source_type="project_experience",
        evidence_origin="sql_fallback",
        vector_id="",
        project_summary=" · ".join(details),
        chunk_text=" · ".join(details),
        organization_raw=project.organization_raw,
        date_range_raw=project.date_range_raw,
        project_tags=tags,
    )
