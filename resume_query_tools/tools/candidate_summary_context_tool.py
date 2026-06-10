from __future__ import annotations

from ..schemas import CandidateSummaryContext
from .candidate_profile_tool import get_candidate_profile
from .project_evidence_tool import get_project_evidence


def build_candidate_summary_context(resume_identity: str) -> CandidateSummaryContext:
    """组装候选人总结所需上下文。

    数据来自候选人 profile 和项目 evidence。这个函数只负责把事实材料整理成
    summary_inputs，真正生成摘要由 `generate_candidate_summary()` 处理。
    """
    candidate = get_candidate_profile(resume_identity)
    evidence = get_project_evidence(resume_identity)
    summary_inputs = {
        "name": candidate.name.value,
        "job_intent": candidate.job_intent.value,
        "skills": [tag.tag_value for tag in candidate.skills],
        "work_experiences": [
            {
                "company_name": item.company_name,
                "job_title_raw": item.job_title_raw,
                "start_date": item.start_date,
                "end_date": item.end_date,
            }
            for item in candidate.work_experiences
        ],
        "education_experiences": [
            {
                "school_name": item.school_name,
                "degree": item.degree,
                "major": item.major,
                "start_date": item.start_date,
                "end_date": item.end_date,
            }
            for item in candidate.education_experiences
        ],
        "projects": [
            {
                "project_id": item.project_id,
                "project_name_raw": item.project_name_raw,
                "tags": [tag.tag_value for tag in item.tags],
            }
            for item in candidate.projects
        ],
        "project_evidence_chunks": [
            {
                "project_id": item.project_id,
                "project_title": item.project_title,
                "chunk_text": item.chunk_text,
                "project_tags": item.project_tags,
            }
            for item in evidence.evidence_chunks
        ],
    }
    return CandidateSummaryContext(
        resume_identity=resume_identity,
        candidate=candidate,
        project_evidence=evidence,
        summary_inputs=summary_inputs,
    )
