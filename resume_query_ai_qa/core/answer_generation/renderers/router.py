"""Route answer layouts to deterministic renderers.

Layout selection is owned by ``answer_layouts.yaml`` and ``layout.py``. This
router only maps the selected layout/task to a renderer and must not introduce
new fact or tool-policy decisions.
"""

from __future__ import annotations

from typing import Any

from resume_query_ai_qa.core.schemas import AggregatedAnswer

from .candidate_set import render_candidate_set, render_scoped_list_evidence
from .common import with_layout_warning
from .comparison import render_comparison
from .decision import render_decision
from .interview import render_question_generation
from .open_grounded import render_boundary, render_open_grounded
from .profile import render_profile_or_fact


def render_rule_answer(query_frame: dict[str, Any], layout_name: str, layout_config: dict[str, Any], context: dict[str, Any]) -> AggregatedAnswer:
    """渲染规则答案并返回。"""
    task_type = str(query_frame.get("task_type") or "")
    intents = set(query_frame.get("intents") or [])
    if {"candidate_list", "evidence_question"} <= intents and context.get("candidates") is not None and "search_candidate_evidence" in set(query_frame.get("successful_tools") or []):
        answer = render_scoped_list_evidence(query_frame, context)
        layout_name = "scoped_list_evidence"
    elif task_type == "boundary_answer" or layout_name == "boundary":
        answer = render_boundary()
    elif task_type == "candidate_comparison_answer" or layout_name == "comparison":
        answer = render_comparison(context)
    elif task_type == "question_generation_answer" or layout_name == "question_generation":
        answer = render_question_generation(query_frame, context)
    elif task_type == "candidate_decision_answer" or layout_name in {"decision_chain", "fit_analysis"}:
        answer = render_decision(layout_name, context)
    elif task_type == "candidate_profile_answer" or "candidate_profile_intro" in (query_frame.get("intents") or []) or layout_name in {"candidate_blocks", "profile", "simple_fact"}:
        answer = render_profile_or_fact(query_frame, layout_name, context)
    elif task_type == "candidate_set_answer":
        answer = render_candidate_set(query_frame, context)
    else:
        answer = render_open_grounded(context)
    return with_layout_warning(answer, layout_name)
