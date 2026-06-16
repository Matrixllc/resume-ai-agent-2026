from __future__ import annotations

from ..config import get_tools_config
from ..schemas import ProjectEvidenceBundle, ProjectEvidenceDTO
from ..stores.vector_reader import ResumeVectorReader, parse_metadata_list
from .candidate_profile_tool import get_candidate_profile
from resume_query_v3.core.data_layer.llm.checker import _clean_project_chunk_text, _clean_project_organization_raw


def get_project_evidence(resume_identity: str) -> ProjectEvidenceBundle:
    """读取候选人的项目级证据包。

    数据来源是 Chroma project chunks，同时用 SQLite profile 里的 project
    manifest 补 project_id。返回值供 QA evidence/search 工具和前端项目展示使用。
    边界：只读证据，不总结、不判断候选人强弱。
    """
    config = get_tools_config()
    candidate = get_candidate_profile(resume_identity)
    reader = ResumeVectorReader(
        persist_dir=config["paths"]["chroma_dir"],
        collection_name=config["storage"]["chroma_collection"],
    )
    project_id_by_title = {item.project_name_raw: item.project_id for item in candidate.projects if item.project_name_raw}
    known_project_ids = {item.project_id for item in candidate.projects if item.project_id}
    known_project_titles = {item.project_name_raw for item in candidate.projects if item.project_name_raw}
    chunks = []
    for row in reader.list_project_chunks(resume_identity, source_type="project_experience"):
        metadata = dict(row.get("metadata", {}) or {})
        project_title = str(metadata.get("project_title", "") or "")
        metadata_project_id = str(metadata.get("project_id", "") or "")
        if candidate.projects and project_title not in known_project_titles and metadata_project_id not in known_project_ids:
            continue
        raw_chunk_text = str(row.get("chunk_text", "") or "")
        organization_raw = _clean_project_organization_raw(
            str(metadata.get("organization_raw", "") or ""),
            project_title=project_title,
            chunk_text=raw_chunk_text,
            project_summary=str(metadata.get("project_summary", "") or ""),
        )
        chunks.append(
            ProjectEvidenceDTO(
                resume_identity=str(metadata.get("resume_identity", "") or resume_identity),
                project_id=project_id_by_title.get(project_title, str(metadata.get("project_id", "") or "")),
                vector_id=str(row.get("vector_id", "") or ""),
                source_type=str(metadata.get("source_type", "") or "project_experience"),
                evidence_origin="chroma",
                project_title=project_title,
                project_summary=str(metadata.get("project_summary", "") or ""),
                chunk_text=_clean_display_chunk_text(
                    text=raw_chunk_text,
                    project_title=project_title,
                    organization_raw=organization_raw,
                    date_range_raw=str(metadata.get("date_range_raw", "") or ""),
                ),
                organization_raw=organization_raw,
                date_range_raw=str(metadata.get("date_range_raw", "") or ""),
                project_tags=parse_metadata_list(metadata.get("project_tags", "[]")),
                evidence_block_ids=parse_metadata_list(metadata.get("evidence_block_ids", "[]")),
                embedding_model=str(metadata.get("embedding_model", "") or ""),
                schema_version=str(metadata.get("schema_version", "") or ""),
            )
        )
    chunks.sort(key=lambda item: item.project_id)
    return ProjectEvidenceBundle(
        resume_identity=resume_identity,
        projects=candidate.projects,
        evidence_chunks=chunks,
    )


def _clean_display_chunk_text(*, text: str, project_title: str, organization_raw: str, date_range_raw: str) -> str:
    """清理展示用 chunk 文本。

    这里只做格式清洗，避免把组织名、日期等重复噪声塞进前端；不改变证据语义。
    """
    safe_organization = organization_raw if len(str(organization_raw or "").strip()) <= 40 else ""
    return _clean_project_chunk_text(
        text,
        project_title=project_title,
        organization_raw=safe_organization,
        date_range_raw=date_range_raw,
        cleanup_config={},
    )
