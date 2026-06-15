"""Plan artifact source and lineage contract checks.

这个文件负责什么：
- 检查 QueryPlan 中候选人集合、排序结果、证据集合的来源和消费链。
- 校验 compiler_templates.yaml 中的 artifact_contracts。

应该从哪个函数读起：
- validate_artifact_source_contract
"""

from __future__ import annotations

from typing import List

from resume_query_ai_qa.core.inspection.plan_inspection import (
    argument_ref_root as _argument_ref_root,
    plan_intent_calls as _intent_calls,
)
from resume_query_ai_qa.core.config import ResumeQAConfig
from resume_query_ai_qa.core.schemas import QueryPlan, RouterOutput, ToolCallSpec

from .plan_semantics import is_hard_domain_condition, router_looks_like_open_recall


def validate_artifact_source_contract(plan: QueryPlan, router_output: RouterOutput | None = None, config: ResumeQAConfig | None = None) -> List[str]:
    """校验计划产物来源、canonical candidate source 和消费链。"""
    errors: List[str] = []
    calls = [call for _intent, items in _intent_calls(plan) for call in items]
    candidate_source_tools = set(config.tools_with_role("candidate_source")) if config else set()
    candidate_sources = [
        call
        for call in calls
        if call.name in candidate_source_tools and (config is None or config.tool_binds_primary_artifact(call.name) or call.name == "resolve_candidate_reference")
    ]
    canonical_bindings = [binding for binding in plan.artifact_bindings if binding.artifact_type == "candidate_collection"]
    if len(canonical_bindings) > 1:
        errors.append("semantic: candidate_collection has multiple canonical artifact bindings")
    canonical = canonical_bindings[0] if canonical_bindings else None
    if canonical and canonical.accepted_producer:
        matched = [
            call
            for call in candidate_sources
            if call.name == canonical.accepted_producer and (call.output_key or "candidate_pool") == canonical.artifact_id
        ]
        if not matched:
            errors.append("semantic: canonical candidate_collection producer is not present in plan")
    required_scope = _required_candidate_scope(router_output)
    if required_scope:
        all_scope_sources = [call.name for call in candidate_sources if call.name == "list_all_candidates"]
        if all_scope_sources:
            errors.append("semantic: filtered candidate scope cannot be produced by all-scope source list_all_candidates")
        hard_domain_required = ({"domain", "domains_any", "domains_all"} & set(required_scope)) and (
            router_output is None
            or (
                not router_looks_like_open_recall(router_output, config)
                and any(is_hard_domain_condition(condition) for condition in router_output.normalized_conditions)
            )
        )
        if hard_domain_required:
            query_only_hybrid = [
                call.name
                for call in candidate_sources
                if call.name == "hybrid_search_candidates" and not (call.arguments or {}).get("domain")
            ]
            if query_only_hybrid and not any(
                call.name == "filter_candidates"
                and any(key in (call.arguments or {}) for key in {"domain", "domains_any", "domains_all"})
                for call in candidate_sources
            ):
                errors.append("semantic: hard domain candidate scope cannot be produced by query-only hybrid_search_candidates")
    source_roots = {call.output_key or "candidate_pool" for call in candidate_sources}
    canonical_root = canonical.artifact_id if canonical else (next(iter(source_roots), "candidate_pool"))
    for call in calls:
        if call.name == "count_candidates":
            root = _argument_ref_root(call.arguments.get("candidates"))
            if root and root != canonical_root:
                errors.append(f"semantic: count_candidates consumes {root}, expected canonical {canonical_root}")
        if call.name == "score_candidates_for_jd":
            root = _argument_ref_root(call.arguments.get("candidate_ids"))
            if root and root not in {canonical_root, "resolved_candidate", "resolved_candidates"}:
                errors.append(f"semantic: score_candidates_for_jd consumes {root}, expected canonical {canonical_root}")
        if call.name == "search_candidate_evidence":
            root = _argument_ref_root(call.arguments.get("candidate_ids"))
            if root and root not in {canonical_root, "resolved_candidate", "resolved_candidates", "ranked_candidates"}:
                errors.append(f"semantic: search_candidate_evidence consumes {root}, expected resolved candidate, ranked candidates, or canonical {canonical_root}")
    for workflow, raw in dict((config.compiler_templates if config else {}).get("workflows", {}) or {}).items():
        template = dict(raw or {})
        markers = {str(item) for item in list(template.get("notes", []) or [])}
        if markers and not markers.intersection(plan.notes or []):
            continue
        for contract_raw in list(template.get("artifact_contracts", []) or []):
            contract = dict(contract_raw or {})
            tool = str(contract.get("tool") or "")
            argument = str(contract.get("argument") or "")
            expected = str(contract.get("expected_ref") or "")
            if expected == "canonical_candidate_collection":
                expected = canonical_root
            call = next((item for item in calls if item.name == tool), None)
            actual = _argument_ref_root((call.arguments or {}).get(argument)) if call else ""
            if actual != expected:
                errors.append(f"semantic: workflow {workflow} tool {tool}.{argument} consumes {actual}, expected {expected}")
    if len({_source_scope_signature(call) for call in candidate_sources}) > 1:
        errors.append("semantic: multiple candidate_collection sources with different scopes")
    return errors


def _required_candidate_scope(router_output: RouterOutput | None) -> dict:
    """从 RouterOutput.normalized_conditions 推导候选来源必须满足的 scope。"""
    if router_output is None:
        return {}
    scope: dict[str, object] = {}
    domains: list[str] = []
    for condition in router_output.normalized_conditions:
        if condition.matched_by.startswith("preference_target:"):
            continue
        value = str(condition.normalized_value or "").strip()
        if not value:
            continue
        if condition.type == "domain":
            domains.append(value)
        elif condition.type in {"skill", "concept", "keyword"}:
            scope.setdefault(condition.type, []).append(value)
    if router_output.context_policy.uses_context and router_output.context_policy.context_ref_type == "candidate_pool":
        scope["context_ref_type"] = "candidate_pool"
    if domains:
        scope["domains_any"] = domains
    return scope


def _source_scope_signature(call: ToolCallSpec) -> str:
    """为 candidate source 工具调用生成 scope 签名，用于发现多来源冲突。"""
    if call.name == "list_all_candidates":
        return "all"
    args = {
        key: value
        for key, value in (call.arguments or {}).items()
        if key in {"domains_any", "domains_all", "skills_all", "concepts_all", "domain", "skills", "keywords", "education_keywords", "project_tags", "job_intent", "candidate_ids"} and value not in ("", [], {}, None)
    }
    if call.name == "hybrid_search_candidates" and (call.arguments or {}).get("query"):
        args["query"] = (call.arguments or {}).get("query")
    return repr(sorted(args.items())) if args else "all"


__all__ = ["validate_artifact_source_contract"]
