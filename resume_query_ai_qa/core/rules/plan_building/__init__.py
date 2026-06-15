"""Tool binding and QueryPlan normalization public exports.

这个包保留历史 ``core.rules.plan_building`` 导入路径，同时把实现按 builders、
query_args、refs、source_policy 等职责拆开。这里不执行工具、不判断 intent。
"""

from .builders import (
    domain_scope_key,
    generic_call_for_tool,
    hybrid_source_call,
    infer_execution_scenario,
    ranking_criteria_tool,
    ranking_has_named_scope,
    should_use_hybrid_recall,
)
from .hints import dedupe_tool_hints, rejected_hint, scored_tool_hints
from .orchestration import normalize_call, normalize_sub_task, sub_task_for_intent, tool_sequence_for_intent
from .query_args import (
    candidate_reference_text,
    filter_args,
    normalize_spaces,
    preference_filter_args,
    preference_recall_query,
    ranking_output_limit,
    sanitize_session_context,
    strip_dialog_context,
    strip_intent_scaffolding,
    tool_query,
    with_context_candidate_ids,
)
from .refs import call_with_structured_refs, convert_argument_refs, replace_ref_root, structured_arg_ref, with_structured_refs
from .source_policy import (
    bind_compound_consumers_to_canonical_source,
    bind_current_calls_to_source,
    candidate_required_scope,
    candidate_source_conflict,
    candidate_source_scope,
    dedupe_repeated_calls,
    default_output_key,
    is_candidate_source_tool,
    last_output_key,
    plan_calls,
    reuse_candidate_source_for_count_list,
    source_signature,
)

__all__ = [
    "bind_compound_consumers_to_canonical_source",
    "bind_current_calls_to_source",
    "call_with_structured_refs",
    "candidate_reference_text",
    "candidate_required_scope",
    "candidate_source_conflict",
    "candidate_source_scope",
    "convert_argument_refs",
    "dedupe_repeated_calls",
    "dedupe_tool_hints",
    "default_output_key",
    "domain_scope_key",
    "filter_args",
    "generic_call_for_tool",
    "hybrid_source_call",
    "infer_execution_scenario",
    "is_candidate_source_tool",
    "last_output_key",
    "normalize_call",
    "normalize_spaces",
    "preference_filter_args",
    "preference_recall_query",
    "normalize_sub_task",
    "plan_calls",
    "ranking_criteria_tool",
    "ranking_has_named_scope",
    "ranking_output_limit",
    "rejected_hint",
    "replace_ref_root",
    "reuse_candidate_source_for_count_list",
    "sanitize_session_context",
    "scored_tool_hints",
    "should_use_hybrid_recall",
    "source_signature",
    "strip_dialog_context",
    "strip_intent_scaffolding",
    "structured_arg_ref",
    "sub_task_for_intent",
    "tool_query",
    "tool_sequence_for_intent",
    "with_context_candidate_ids",
    "with_structured_refs",
]
