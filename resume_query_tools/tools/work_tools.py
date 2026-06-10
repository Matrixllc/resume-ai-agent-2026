from __future__ import annotations

from typing import List

from ..schemas import WorkExperienceDTO
from .candidate_profile_tool import get_candidate_profile


def list_work_experiences(resume_identity: str) -> List[WorkExperienceDTO]:
    """读取候选人的结构化工作经历。

    当前直接复用 `get_candidate_profile()`，保证工作经历和候选人详情使用同一套
    SQLite 读取逻辑。它只返回事实 DTO，不做经历解读。
    """
    return get_candidate_profile(resume_identity).work_experiences
