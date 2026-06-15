from __future__ import annotations

from typing import Any, Dict, List

from resume_query_ai_qa.core.schemas import CandidateScore, ResumeQAState

from .qa_evidence import _used_evidence_refs
from .qa_schemas import QAAskResponse
from .qa_trace import _public_trace_summary, _trace_summary


def _response_from_state(state: ResumeQAState, *, debug: bool) -> QAAskResponse:
    answer = state.answer.answer if state.answer else ""
    status = state.trace.final_status
    if status not in {"ok", "needs_clarification", "failed"}:
        status = "failed"
    trace = _trace_summary(state) if debug else _public_trace_summary(state)
    return QAAskResponse(
        status=status,
        answer=answer,
        clarification_required=state.clarification_required,
        clarification_question=state.clarification_question,
        clarification_options=state.clarification_options,
        used_evidence_refs=_used_evidence_refs(state),
        ranking=_ranking_from_state(state),
        comparison_profiles=_comparison_profiles(state),
        comparison_candidate_ids=_comparison_candidate_ids(state),
        updated_session_context=state.updated_session_context or state.session_context,
        trace=trace,
    )


def _ranking_from_state(state: ResumeQAState) -> List[Dict[str, Any]]:
    for result in reversed(state.tool_results):
        if not result.ok or result.tool_name != "rank_candidates":
            continue
        scores = result.data or []
        return [
            (item if isinstance(item, CandidateScore) else CandidateScore.model_validate(item)).model_dump()
            for item in scores
        ]
    return []


def _comparison_candidate_ids(state: ResumeQAState) -> List[str]:
    for result in reversed(state.tool_results):
        if not result.ok or result.tool_name != "build_comparison_pack" or not isinstance(result.data, dict):
            continue
        return [str(item) for item in result.data.get("candidate_ids", []) if str(item).strip()]
    return []


def _comparison_profiles(state: ResumeQAState) -> List[Dict[str, Any]]:
    for result in reversed(state.tool_results):
        if not result.ok or result.tool_name != "build_comparison_pack" or not isinstance(result.data, dict):
            continue
        candidate_ids = [str(item) for item in result.data.get("candidate_ids", []) if str(item).strip()]
        profiles = result.data.get("profiles", {})
        if not isinstance(profiles, dict):
            return []
        output: List[Dict[str, Any]] = []
        for candidate_id in candidate_ids:
            profile = profiles.get(candidate_id, {})
            if not isinstance(profile, dict):
                continue
            output.append(
                {
                    "resume_identity": candidate_id,
                    "name": profile.get("name", ""),
                    "job_intent": profile.get("job_intent", ""),
                    "work_experiences": profile.get("work_experiences", []),
                    "projects": profile.get("projects", []),
                }
            )
        return output
    return []
