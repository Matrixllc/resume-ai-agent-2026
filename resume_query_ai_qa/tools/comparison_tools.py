"""Fact packs for pairwise candidate comparison."""

from __future__ import annotations

from typing import Any, Dict, List

from .candidate_tools import get_candidate_brief
from .evidence_tools import get_candidate_evidence
from .profile_tools import get_candidate_profile_intro


def build_comparison_pack(candidate_ids: List[str], domain: str | None = None, query: str | None = None) -> Dict[str, Any]:
    """构造双人比较所需的事实包。

    输入必须正好两个 candidate_id。输出包括两人的 brief、profile 和项目证据。
    它只准备事实材料，不直接选赢家；最终比较表达由 aggregator 基于这些事实
    完成，answer_validator 会检查证据是否足够。
    """
    if len(candidate_ids) != 2:
        raise ValueError("build_comparison_pack requires exactly 2 candidate ids")
    evidence_query = query or domain or None
    return {
        "candidate_ids": candidate_ids,
        "domain": domain or "",
        "query": evidence_query or "",
        "briefs": [_comparison_brief(candidate_id) for candidate_id in candidate_ids],
        "profiles": {
            candidate_id: get_candidate_profile_intro(candidate_id)
            for candidate_id in candidate_ids
        },
        "evidence": {
            candidate_id: [
                item.model_dump()
                for item in get_candidate_evidence(candidate_id, query=evidence_query, limit=6)
            ]
            for candidate_id in candidate_ids
        },
    }


def _comparison_brief(candidate_id: str) -> Dict[str, Any]:
    """获取比较候选人摘要并返回。"""
    brief = get_candidate_brief(candidate_id).model_dump()
    # Skill/domain tag refs are weak evidence and create noisy validation
    # warnings. Pair comparison uses the strong project evidence field below.
    brief["evidence_refs"] = []
    return brief
