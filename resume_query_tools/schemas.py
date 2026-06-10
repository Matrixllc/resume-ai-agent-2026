from __future__ import annotations

from typing import Any, Dict, List

from pydantic import BaseModel, Field


class CandidateListItem(BaseModel):
    resume_identity: str
    source_path: str = ""
    name: str = ""
    job_intent: str = ""
    location_raw: str = ""
    document_profile: str = ""
    resolve_mode: str = ""
    project_count: int = 0
    work_count: int = 0


class CandidateListResponse(BaseModel):
    candidates: List[CandidateListItem] = Field(default_factory=list)


class ScoredField(BaseModel):
    value: Any = ""
    confidence: float = 0.0
    source: str = ""
    evidence_block_ids: List[str] = Field(default_factory=list)


class WorkExperienceDTO(BaseModel):
    work_ref: str = ""
    company_name: str = ""
    job_title_raw: str = ""
    start_date: str = ""
    end_date: str = ""
    location: str = ""
    raw_line: str = ""
    confidence: float = 0.0
    source: str = ""
    evidence_block_ids: List[str] = Field(default_factory=list)


class EducationExperienceDTO(BaseModel):
    school_name: str = ""
    degree: str = ""
    major: str = ""
    start_date: str = ""
    end_date: str = ""
    raw_line: str = ""
    confidence: float = 0.0
    source: str = ""
    evidence_block_ids: List[str] = Field(default_factory=list)


class TagDTO(BaseModel):
    tag_type: str = ""
    tag_value: str = ""
    raw_value: str = ""
    confidence: float = 0.0
    source: str = ""
    evidence_block_ids: List[str] = Field(default_factory=list)


class ProjectManifestDTO(BaseModel):
    project_id: str = ""
    project_name_raw: str = ""
    project_source_type: str = ""
    parent_work_experience_ref: str = ""
    organization_raw: str = ""
    date_range_raw: str = ""
    role_raw: str = ""
    role_normalized: str = ""
    confidence: float = 0.0
    source: str = ""
    evidence_block_ids: List[str] = Field(default_factory=list)
    tags: List[TagDTO] = Field(default_factory=list)


class CandidateQualityDTO(BaseModel):
    document_profile: str = ""
    resolve_mode: str = ""
    compression_ratio: float = 0.0
    missing_required_fields: List[str] = Field(default_factory=list)
    work_count: int = 0
    education_count: int = 0
    project_count: int = 0


class CandidateDetail(BaseModel):
    resume_identity: str
    source_path: str = ""
    name: ScoredField = Field(default_factory=ScoredField)
    contact: Dict[str, ScoredField] = Field(default_factory=dict)
    job_intent: ScoredField = Field(default_factory=ScoredField)
    location_raw: ScoredField = Field(default_factory=ScoredField)
    overview_raw: ScoredField = Field(default_factory=ScoredField)
    skills: List[TagDTO] = Field(default_factory=list)
    languages: List[TagDTO] = Field(default_factory=list)
    certifications_or_scores: List[TagDTO] = Field(default_factory=list)
    work_experiences: List[WorkExperienceDTO] = Field(default_factory=list)
    education_experiences: List[EducationExperienceDTO] = Field(default_factory=list)
    projects: List[ProjectManifestDTO] = Field(default_factory=list)
    tags: List[TagDTO] = Field(default_factory=list)
    quality: CandidateQualityDTO = Field(default_factory=CandidateQualityDTO)


class ProjectEvidenceDTO(BaseModel):
    resume_identity: str = ""
    project_id: str = ""
    vector_id: str = ""
    project_title: str = ""
    project_summary: str = ""
    chunk_text: str = ""
    organization_raw: str = ""
    date_range_raw: str = ""
    project_tags: List[str] = Field(default_factory=list)
    evidence_block_ids: List[str] = Field(default_factory=list)
    embedding_model: str = ""
    schema_version: str = ""


class ProjectEvidenceBundle(BaseModel):
    resume_identity: str
    projects: List[ProjectManifestDTO] = Field(default_factory=list)
    evidence_chunks: List[ProjectEvidenceDTO] = Field(default_factory=list)


class ClassifiedProjectsResponse(BaseModel):
    resume_identity: str
    ordinary_projects: List[ProjectManifestDTO] = Field(default_factory=list)
    work_embedded_projects: List[ProjectManifestDTO] = Field(default_factory=list)
    work_experiences: List[WorkExperienceDTO] = Field(default_factory=list)
    evidence_chunks: List[ProjectEvidenceDTO] = Field(default_factory=list)


class CandidateSummaryContext(BaseModel):
    resume_identity: str
    candidate: CandidateDetail
    project_evidence: ProjectEvidenceBundle
    summary_inputs: Dict[str, Any] = Field(default_factory=dict)


class SummarySections(BaseModel):
    overall_summary: str = ""
    personal_summary: str = ""
    project_summary: str = ""
    work_experience_summary: str = ""
    strengths: List[str] = Field(default_factory=list)
    risks_or_missing_info: List[str] = Field(default_factory=list)


class CandidateSummaryResponse(BaseModel):
    resume_identity: str
    summary: str = ""
    summary_sections: SummarySections = Field(default_factory=SummarySections)
    summary_inputs: Dict[str, Any] = Field(default_factory=dict)
    provider: str = ""
    model: str = ""
    llm_error: str = ""


class DisplayField(BaseModel):
    value: str = ""


class DisplayTag(BaseModel):
    tag_type: str = ""
    tag_value: str = ""


class DisplayCandidateListItem(BaseModel):
    resume_identity: str
    file_name: str = ""
    name: str = ""
    job_intent: str = ""
    location_raw: str = ""
    project_count: int = 0
    work_count: int = 0


class DisplayCandidateListResponse(BaseModel):
    candidates: List[DisplayCandidateListItem] = Field(default_factory=list)


class DisplayWorkExperience(BaseModel):
    work_ref: str = ""
    company_name: str = ""
    job_title_raw: str = ""
    start_date: str = ""
    end_date: str = ""
    location: str = ""
    raw_line: str = ""


class DisplayWorkProfile(BaseModel):
    years_label: str = ""
    total_years: float = 0.0
    confidence_label: str = ""
    domains: List[str] = Field(default_factory=list)
    roles: List[str] = Field(default_factory=list)
    companies: List[str] = Field(default_factory=list)


class DisplayEducationExperience(BaseModel):
    school_name: str = ""
    degree: str = ""
    major: str = ""
    start_date: str = ""
    end_date: str = ""


class DisplayProject(BaseModel):
    project_id: str = ""
    project_name_raw: str = ""
    project_source_type: str = ""
    parent_work_experience_ref: str = ""
    organization_raw: str = ""
    date_range_raw: str = ""
    role_raw: str = ""
    role_normalized: str = ""
    tags: List[DisplayTag] = Field(default_factory=list)


class DisplayEvidenceChunk(BaseModel):
    project_id: str = ""
    project_title: str = ""
    project_summary: str = ""
    chunk_text: str = ""
    organization_raw: str = ""
    date_range_raw: str = ""
    project_tags: List[str] = Field(default_factory=list)


class DisplayCandidateDetail(BaseModel):
    resume_identity: str
    file_name: str = ""
    name: DisplayField = Field(default_factory=DisplayField)
    contact: Dict[str, DisplayField] = Field(default_factory=dict)
    job_intent: DisplayField = Field(default_factory=DisplayField)
    location_raw: DisplayField = Field(default_factory=DisplayField)
    skills: List[DisplayTag] = Field(default_factory=list)
    languages: List[DisplayTag] = Field(default_factory=list)
    certifications_or_scores: List[DisplayTag] = Field(default_factory=list)
    work_profile: DisplayWorkProfile = Field(default_factory=DisplayWorkProfile)
    work_experiences: List[DisplayWorkExperience] = Field(default_factory=list)
    education_experiences: List[DisplayEducationExperience] = Field(default_factory=list)
    tags: List[DisplayTag] = Field(default_factory=list)


class DisplayClassifiedProjectsResponse(BaseModel):
    resume_identity: str
    ordinary_projects: List[DisplayProject] = Field(default_factory=list)
    work_embedded_projects: List[DisplayProject] = Field(default_factory=list)
    work_experiences: List[DisplayWorkExperience] = Field(default_factory=list)
    evidence_chunks: List[DisplayEvidenceChunk] = Field(default_factory=list)
