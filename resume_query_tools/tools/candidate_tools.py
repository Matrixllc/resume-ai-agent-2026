from __future__ import annotations

from pathlib import Path

from ..config import get_tools_config
from ..schemas import CandidateListItem, CandidateListResponse, DisplayCandidateListItem, DisplayCandidateListResponse
from ..stores.sql_reader import ResumeSqlReader
from .candidate_profile_tool import get_candidate_profile


def list_candidates() -> CandidateListResponse:
    """读取候选人轻量列表。

    数据来源是 v3 写入的 SQLite。这个函数只返回列表页和筛选所需的基础字段，
    不读取项目证据，也不做排序/推荐判断。
    """
    config = get_tools_config()
    reader = ResumeSqlReader(config["paths"]["structured_store_file"])
    rows = reader.list_candidates()
    return CandidateListResponse(
        candidates=[
            CandidateListItem(
                resume_identity=str(row.get("resume_identity", "") or ""),
                source_path=str(row.get("source_path", "") or ""),
                name=str(row.get("name", "") or ""),
                job_intent=str(row.get("job_intent", "") or ""),
                location_raw=str(row.get("location_raw", "") or ""),
                document_profile=str(row.get("document_profile", "") or ""),
                resolve_mode=str(row.get("resolve_mode", "") or ""),
                project_count=int(row.get("project_count", 0) or 0),
                work_count=int(row.get("work_count", 0) or 0),
            )
            for row in rows
        ]
    )


def list_candidates_display() -> DisplayCandidateListResponse:
    """返回前端列表展示 DTO。

    它基于 `list_candidates()` 做字段裁剪和文件名格式化，避免前端直接接触
    数据库行结构。
    """
    full = list_candidates()
    return DisplayCandidateListResponse(
        candidates=[
            DisplayCandidateListItem(
                resume_identity=item.resume_identity,
                file_name=Path(item.source_path).name if item.source_path else "",
                name=item.name,
                job_intent=item.job_intent,
                location_raw=item.location_raw,
                project_count=item.project_count,
                work_count=item.work_count,
            )
            for item in full.candidates
        ]
    )
