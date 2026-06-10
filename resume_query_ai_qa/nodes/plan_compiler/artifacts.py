"""Compatibility wrapper for canonical artifact bindings."""

from resume_query_ai_qa.core.inspection.plan_artifacts import (
    artifact_bindings_from_plan,
    argument_ref_roots,
    candidate_id_refs_from_call,
    ranking_required_scope,
    source_artifact_id_for_call,
    with_artifact_bindings,
)

__all__ = [
    "artifact_bindings_from_plan",
    "argument_ref_roots",
    "candidate_id_refs_from_call",
    "ranking_required_scope",
    "source_artifact_id_for_call",
    "with_artifact_bindings",
]
