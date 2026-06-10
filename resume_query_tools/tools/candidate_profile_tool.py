from __future__ import annotations

from pathlib import Path
import re
from datetime import date
from typing import Dict, List

from ..config import get_tools_config
from ..schemas import (
    CandidateDetail,
    CandidateQualityDTO,
    DisplayCandidateDetail,
    DisplayEducationExperience,
    DisplayField,
    DisplayTag,
    DisplayWorkProfile,
    DisplayWorkExperience,
    EducationExperienceDTO,
    ProjectManifestDTO,
    ScoredField,
    TagDTO,
    WorkExperienceDTO,
)
from ..stores.sql_reader import ResumeSqlReader, parse_evidence_ids


def get_candidate_profile(resume_identity: str) -> CandidateDetail:
    """读取候选人完整结构化详情。

    数据来源是 SQLite：候选人主表、工作经历、教育经历、候选人标签、项目
    manifest、项目标签。这个函数是 tools 层的核心事实读取入口，不调用 LLM，
    不读 Chroma evidence，也不生成评价结论。
    """
    config = get_tools_config()
    reader = ResumeSqlReader(config["paths"]["structured_store_file"])
    candidate = reader.get_candidate(resume_identity)
    if not candidate:
        raise ValueError(f"candidate not found: {resume_identity}")
    work_rows = reader.list_work_experiences(resume_identity)
    education_rows = reader.list_education_experiences(resume_identity)
    tag_rows = reader.list_candidate_tags(resume_identity)
    project_rows = reader.list_projects(resume_identity)
    project_tag_rows = reader.list_project_tags(resume_identity)
    tags = [_tag_from_row(row) for row in tag_rows]
    projects = _project_rows(project_rows, project_tag_rows)
    return CandidateDetail(
        resume_identity=resume_identity,
        source_path=str(candidate.get("source_path", "") or ""),
        name=_candidate_field(candidate, "name"),
        contact={
            "phone": _candidate_field(candidate, "phone"),
            "email": _candidate_field(candidate, "email"),
            "wechat": _candidate_field(candidate, "wechat"),
        },
        job_intent=_candidate_field(candidate, "job_intent"),
        location_raw=_candidate_field(candidate, "location_raw"),
        overview_raw=_candidate_field(candidate, "overview_raw"),
        skills=[tag for tag in tags if tag.tag_type in {"skill", "raw_skill", "concept"}],
        languages=[tag for tag in tags if tag.tag_type == "language"],
        certifications_or_scores=[tag for tag in tags if tag.tag_type == "certification"],
        work_experiences=[_work_from_row(row) for row in work_rows],
        education_experiences=[_education_from_row(row) for row in education_rows],
        projects=projects,
        tags=tags,
        quality=_quality(candidate, work_rows, education_rows, projects),
    )


def get_candidate_profile_display(resume_identity: str) -> DisplayCandidateDetail:
    """返回前端展示用候选人详情。

    它基于完整 `CandidateDetail` 做展示字段整理，包括工作年限估算和标签裁剪。
    展示 DTO 是 API/前端契约，避免前端直接理解底层 SQL schema。
    """
    detail = get_candidate_profile(resume_identity)
    display_tags = _display_tags(detail.tags)
    return DisplayCandidateDetail(
        resume_identity=detail.resume_identity,
        file_name=Path(detail.source_path).name if detail.source_path else "",
        name=DisplayField(value=str(detail.name.value or "")),
        contact={
            key: DisplayField(value=str(value.value or ""))
            for key, value in detail.contact.items()
        },
        job_intent=DisplayField(value=str(detail.job_intent.value or "")),
        location_raw=DisplayField(value=str(detail.location_raw.value or "")),
        skills=_display_tags([tag for tag in detail.tags if tag.tag_type == "skill"]),
        languages=_display_tags(detail.languages),
        certifications_or_scores=_display_tags(detail.certifications_or_scores),
        work_profile=_display_work_profile(detail.work_experiences, display_tags),
        work_experiences=[
            DisplayWorkExperience(
                work_ref=item.work_ref,
                company_name=item.company_name,
                job_title_raw=item.job_title_raw,
                start_date=item.start_date,
                end_date=item.end_date,
                location=item.location,
                raw_line=item.raw_line,
            )
            for item in detail.work_experiences
        ],
        education_experiences=[
            DisplayEducationExperience(
                school_name=item.school_name,
                degree=item.degree,
                major=item.major,
                start_date=item.start_date,
                end_date=item.end_date,
            )
            for item in detail.education_experiences
        ],
        tags=display_tags,
    )


def _candidate_field(row: Dict[str, object], field_name: str) -> ScoredField:
    return ScoredField(
        value=str(row.get(field_name, "") or ""),
        confidence=1.0 if str(row.get(field_name, "") or "").strip() else 0.0,
        source="sql",
        evidence_block_ids=[],
    )


def _work_from_row(row: Dict[str, object]) -> WorkExperienceDTO:
    return WorkExperienceDTO(
        work_ref=str(row.get("work_ref", "") or ""),
        company_name=str(row.get("company_name", "") or ""),
        job_title_raw=str(row.get("job_title_raw", "") or ""),
        start_date=str(row.get("start_date", "") or ""),
        end_date=str(row.get("end_date", "") or ""),
        location=str(row.get("location", "") or ""),
        raw_line=str(row.get("raw_line", "") or ""),
        confidence=float(row.get("confidence", 0.0) or 0.0),
        source=str(row.get("source", "") or ""),
        evidence_block_ids=parse_evidence_ids(row),
    )


def _education_from_row(row: Dict[str, object]) -> EducationExperienceDTO:
    return EducationExperienceDTO(
        school_name=str(row.get("school_name", "") or ""),
        degree=str(row.get("degree", "") or ""),
        major=str(row.get("major", "") or ""),
        start_date=str(row.get("start_date", "") or ""),
        end_date=str(row.get("end_date", "") or ""),
        raw_line=str(row.get("raw_line", "") or ""),
        confidence=float(row.get("confidence", 0.0) or 0.0),
        source=str(row.get("source", "") or ""),
        evidence_block_ids=parse_evidence_ids(row),
    )


def _project_rows(project_rows: List[Dict[str, object]], project_tag_rows: List[Dict[str, object]]) -> List[ProjectManifestDTO]:
    tags_by_project: Dict[str, List[TagDTO]] = {}
    for row in project_tag_rows:
        project_id = str(row.get("project_id", "") or "")
        tags_by_project.setdefault(project_id, []).append(_tag_from_row(row))
    return [
        ProjectManifestDTO(
            project_id=str(row.get("project_id", "") or ""),
            project_name_raw=str(row.get("project_name_raw", "") or ""),
            project_source_type=str(row.get("project_source_type", "") or ""),
            parent_work_experience_ref=str(row.get("parent_work_experience_ref", "") or ""),
            organization_raw=str(row.get("organization_raw", "") or ""),
            date_range_raw=str(row.get("date_range_raw", "") or ""),
            role_raw=str(row.get("role_raw", "") or ""),
            role_normalized=str(row.get("role_normalized", "") or ""),
            confidence=float(row.get("confidence", 0.0) or 0.0),
            source=str(row.get("source", "") or ""),
            evidence_block_ids=parse_evidence_ids(row),
            tags=tags_by_project.get(str(row.get("project_id", "") or ""), []),
        )
        for row in project_rows
    ]


def _tag_from_row(row: Dict[str, object]) -> TagDTO:
    return TagDTO(
        tag_type=str(row.get("tag_type", "") or ""),
        tag_value=str(row.get("tag_value", "") or ""),
        raw_value=str(row.get("raw_value", "") or ""),
        confidence=float(row.get("confidence", 0.0) or 0.0),
        source=str(row.get("source", "") or ""),
        evidence_block_ids=parse_evidence_ids(row),
    )


def _display_tags(tags: List[TagDTO]) -> List[DisplayTag]:
    seen = set()
    output: List[DisplayTag] = []
    for tag in tags:
        tag_type = str(tag.tag_type or "").strip()
        tag_value = str(tag.tag_value or "").strip()
        key = (tag_type, tag_value.lower())
        if not tag_type or not tag_value or key in seen:
            continue
        seen.add(key)
        output.append(DisplayTag(tag_type=tag_type, tag_value=tag_value))
    return output


def _display_work_profile(work_experiences: List[WorkExperienceDTO], tags: List[DisplayTag]) -> DisplayWorkProfile:
    total_years = _estimate_work_years(work_experiences)
    domains = _unique_values(tag.tag_value for tag in tags if tag.tag_type in {"domain", "experience"})
    roles = _unique_values(item.job_title_raw for item in work_experiences)
    companies = _unique_values(item.company_name for item in work_experiences)
    confidence_label = "高" if total_years > 0 and work_experiences else ("中" if work_experiences else "待复核")
    return DisplayWorkProfile(
        years_label=_format_years_label(total_years),
        total_years=total_years,
        confidence_label=confidence_label,
        domains=domains[:6],
        roles=roles[:5],
        companies=companies[:6],
    )


def _estimate_work_years(work_experiences: List[WorkExperienceDTO]) -> float:
    intervals: List[tuple[int, int]] = []
    today = date.today()
    for item in work_experiences:
        start = _month_index(item.start_date)
        end = _month_index(item.end_date)
        if start is None:
            continue
        if end is None and _is_present_date(item.end_date):
            end = today.year * 12 + today.month
        if end is None:
            end = start
        if end < start:
            start, end = end, start
        intervals.append((start, end))
    if not intervals:
        return 0.0
    intervals.sort()
    merged: List[tuple[int, int]] = []
    for start, end in intervals:
        if not merged or start > merged[-1][1] + 1:
            merged.append((start, end))
        else:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
    months = sum(end - start + 1 for start, end in merged)
    return round(months / 12, 1)


def _month_index(value: str) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    match = re.search(r"(19|20)\d{2}(?:[-./年](0?[1-9]|1[0-2]))?", text)
    if not match:
        return None
    year = int(match.group(0)[:4])
    month_match = re.search(r"(?:[-./年])(0?[1-9]|1[0-2])", match.group(0))
    month = int(month_match.group(1)) if month_match else 1
    return year * 12 + month


def _is_present_date(value: str) -> bool:
    text = str(value or "").strip().lower()
    return any(token in text for token in ("至今", "present", "current", "now"))


def _format_years_label(total_years: float) -> str:
    if total_years <= 0:
        return "年限待复核"
    if total_years < 1:
        return "不足 1 年"
    years = int(total_years)
    if total_years - years >= 0.5:
        return f"{years}.5 年"
    return f"{years} 年"


def _unique_values(values) -> List[str]:
    seen = set()
    output: List[str] = []
    for value in values:
        text = str(value or "").strip()
        key = re.sub(r"\s+", "", text).lower()
        if not key or key in seen:
            continue
        seen.add(key)
        output.append(text)
    return output


def _quality(
    candidate: Dict[str, object],
    work_rows: List[Dict[str, object]],
    education_rows: List[Dict[str, object]],
    projects: List[ProjectManifestDTO],
) -> CandidateQualityDTO:
    missing = [
        name
        for name in ("name", "phone", "email")
        if not str(candidate.get(name, "") or "").strip()
    ]
    return CandidateQualityDTO(
        document_profile=str(candidate.get("document_profile", "") or ""),
        resolve_mode=str(candidate.get("resolve_mode", "") or ""),
        compression_ratio=float(candidate.get("compression_ratio", 0.0) or 0.0),
        missing_required_fields=missing,
        work_count=len(work_rows),
        education_count=len(education_rows),
        project_count=len(projects),
    )
