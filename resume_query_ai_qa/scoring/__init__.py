"""Public exports for deterministic JD scoring.

这个包只导出评分内核函数。executor 不直接调用这里，而是通过
tools/scoring_tools.py 的工具 adapter 间接调用。
"""

from .jd import (
    extract_jd_criteria,
    load_default_jd_criteria,
    load_general_resume_criteria,
    rank_candidates,
    score_candidate_material_for_jd,
)

__all__ = [
    "extract_jd_criteria",
    "load_default_jd_criteria",
    "load_general_resume_criteria",
    "rank_candidates",
    "score_candidate_material_for_jd",
]
