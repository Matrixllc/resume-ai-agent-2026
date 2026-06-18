"""ToolCallSpec builders keyed by tool ``binding_kind``."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from resume_query_ai_qa.core.config import ResumeQAConfig, load_config
from resume_query_ai_qa.core.rules.context_resolver import candidate_ids_for_context
from resume_query_ai_qa.core.rules.execution_policy_rules import scenario_for_intent
from resume_query_ai_qa.core.schemas import RouterOutput, ToolCallSpec

from .query_args import candidate_reference_text, evidence_scope_from_question, filter_args, preference_filter_args, preference_recall_query, ranking_filter_args, ranking_target_text, sanitize_session_context, tool_query
from .refs import structured_arg_ref
from .source_policy import last_output_key


@dataclass(frozen=True)
class BuildContext:
    """计划构造器的只读输入上下文，集中传递规则事实和前序调用引用。"""
    tool_name: str
    intent: str
    question: str
    router_output: RouterOutput
    session_context: dict | None
    previous_calls: list[ToolCallSpec]
    config: ResumeQAConfig
    query: str
    source: str
    criteria: str
    scores: str


Builder = Callable[[BuildContext], ToolCallSpec | None]


def hybrid_source_call(
    query: str,
    router_output: RouterOutput,
    session_context: dict | None,
    *,
    output_key: str = "candidate_pool",
    config: ResumeQAConfig | None = None,
) -> ToolCallSpec:
    """构建混合召回工具调用并返回。"""
    cfg = config or load_config()
    tool_name = cfg.first_tool_with_binding_kind("semantic_search")
    arguments: dict[str, Any] = {"query": query}
    candidate_ids = candidate_ids_for_context(router_output.context_policy, session_context)
    if candidate_ids:
        arguments["candidate_ids"] = candidate_ids
    return ToolCallSpec(name=tool_name, arguments=arguments, output_key=output_key)


def generic_call_for_tool(
    tool_name: str,
    intent: str,
    question: str,
    router_output: RouterOutput,
    session_context: dict | None,
    previous_calls: list[ToolCallSpec],
    *,
    config: ResumeQAConfig | None = None,
) -> ToolCallSpec | None:
    """按工具绑定类型构建工具调用并返回。"""
    cfg = config or load_config()
    binding_kind = cfg.tool_binding_kind(tool_name)
    context = BuildContext(
        tool_name=tool_name,
        intent=intent,
        question=question,
        router_output=router_output,
        session_context=session_context,
        previous_calls=previous_calls,
        config=cfg,
        query=tool_query(question, intent, router_output),
        source=last_output_key(previous_calls, cfg.tools_with_role("candidate_source")),
        criteria=last_output_key(previous_calls, cfg.tools_with_role("criteria_source")),
        scores=last_output_key(previous_calls, cfg.tools_with_role("score_source")),
    )
    builder = _BUILDERS.get(binding_kind)
    if builder is None:
        return None
    return builder(context)


def should_use_hybrid_recall(question: str, router_output: RouterOutput) -> bool:
    """判断候选人筛选是否使用开放召回并返回布尔值。"""
    return scenario_for_intent(router_output, "candidate_filter") == "open_recall"


def infer_execution_scenario(question: str, router_output: RouterOutput, intent: str) -> str:
    """推断执行场景并返回。"""
    return scenario_for_intent(router_output, intent)


def ranking_criteria_tool(router_output: RouterOutput | None, config: ResumeQAConfig | None = None) -> str:
    """获取排序评分标准工具并返回。"""
    config = config or load_config()
    role = "default_jd_criteria" if router_output and router_output.requires_jd else "general_ranking_criteria"
    return config.first_tool_with_role(role)


def ranking_has_named_scope(router_output: RouterOutput | None) -> bool:
    """判断排序是否限定具名候选人并返回布尔值。"""
    return bool(router_output and any(condition.type == "candidate_name" for condition in router_output.normalized_conditions))


def has_named_candidate_scope(router_output: RouterOutput | None) -> bool:
    """判断本轮是否有真实候选人姓名约束并返回布尔值。"""
    return bool(router_output and any(condition.type == "candidate_name" for condition in router_output.normalized_conditions))


def context_collection_candidate_ids(router_output: RouterOutput, session_context: dict | None) -> list[str]:
    """获取可直接作为候选集合使用的上下文候选人标识。"""
    if has_named_candidate_scope(router_output):
        return []
    configured = {
        str(item)
        for item in list(dict(load_config().router_rules.get("candidate_scope_rules", {}) or {}).get("context_candidate_ref_types", []) or [])
    }
    if router_output.context_policy.context_ref_type not in (configured or {"ranking_top", "ranking_top_k", "candidate_pool", "comparison_pair"}):
        return []
    return candidate_ids_for_context(router_output.context_policy, session_context)


def domain_scope_key(router_output: RouterOutput | None) -> str:
    """获取领域范围键并返回。"""
    if router_output is None:
        return ""
    return next(
        (str(condition.normalized_value) for condition in router_output.normalized_conditions if condition.type == "domain"),
        "",
    )


def _list_candidates(context: BuildContext) -> ToolCallSpec:
    """列出候选人集合并返回。"""
    return ToolCallSpec(name=context.tool_name, output_key=context.config.default_output_key(context.tool_name))


def _structured_filter(context: BuildContext) -> ToolCallSpec | None:
    """构建结构化筛选工具调用并返回。"""
    if context.intent in {"candidate_ranking", "jd_scoring"} and ranking_has_named_scope(context.router_output):
        return generic_call_for_tool(
            context.config.first_tool_with_binding_kind("resolve_reference"),
            context.intent,
            context.question,
            context.router_output,
            context.session_context,
            context.previous_calls,
            config=context.config,
        )
    context_ids = candidate_ids_for_context(context.router_output.context_policy, context.session_context)
    if context.intent in {"candidate_ranking", "jd_scoring"} and context_ids:
        return ToolCallSpec(
            name=context.tool_name,
            arguments={"candidate_ids": context_ids},
            output_key="candidate_pool",
        )
    if context.intent in {"candidate_ranking", "jd_scoring"}:
        args = ranking_filter_args(context.question, context.router_output, context.session_context)
        if not args:
            return ToolCallSpec(
                name=context.config.first_tool_with_binding_kind("list_candidates"),
                output_key="candidate_pool",
            )
        return ToolCallSpec(
            name=context.tool_name,
            arguments=args,
            output_key="candidate_pool",
        )
    args = filter_args(context.question, context.router_output, context.session_context)
    if not args:
        args = preference_filter_args(context.question, context.router_output, context.session_context)
    if not args:
        return None
    return ToolCallSpec(
        name=context.tool_name,
        arguments=args,
        output_key="candidate_pool",
    )


def _semantic_search(context: BuildContext) -> ToolCallSpec | None:
    """构建语义检索工具调用并返回。"""
    query = context.query or preference_recall_query(context.question, context.router_output)
    if not query:
        return None
    return hybrid_source_call(query, context.router_output, context.session_context, config=context.config)


def _resolve_reference(context: BuildContext) -> ToolCallSpec:
    """解析引用并返回。"""
    candidate_ids = context_collection_candidate_ids(context.router_output, context.session_context)
    if candidate_ids:
        return ToolCallSpec(
            name=context.config.first_tool_with_binding_kind("structured_filter"),
            arguments={"candidate_ids": candidate_ids},
            output_key="candidate_pool",
        )
    output_key = "resolved_candidates" if context.intent == "candidate_compare_pair" else "resolved_candidate"
    return ToolCallSpec(
        name=context.tool_name,
        arguments={
            "text": candidate_reference_text(context.question, context.router_output),
            "session_context": sanitize_session_context(context.session_context),
        },
        output_key=output_key,
    )


def _count_collection(context: BuildContext) -> ToolCallSpec:
    """构建候选人集合计数调用并返回。"""
    source = context.source or "candidate_pool"
    return ToolCallSpec(
        name=context.tool_name,
        arguments={"candidates": structured_arg_ref(source, ["resume_identity"], mapped=True)},
        depends_on=[source],
    )


def _single_profile(context: BuildContext) -> ToolCallSpec:
    """获取单个候选人画像并返回。"""
    source = context.source or "resolved_candidate"
    return ToolCallSpec(
        name=context.tool_name,
        arguments={"resume_identity": _single_candidate_ref(source)},
        output_key=context.config.default_output_key(context.tool_name),
        depends_on=[source],
    )


def _multi_profile(context: BuildContext) -> ToolCallSpec:
    """获取多个候选人画像并返回。"""
    source = context.source or "resolved_candidate"
    return ToolCallSpec(
        name=context.tool_name,
        arguments={"candidate_ids": _candidate_ids_ref(source)},
        output_key=context.config.default_output_key(context.tool_name),
        depends_on=[source],
    )


def _single_evidence(context: BuildContext) -> ToolCallSpec:
    """获取单个证据并返回。"""
    source = context.source or "resolved_candidate"
    return ToolCallSpec(
        name=context.tool_name,
        arguments={"resume_identity": _single_candidate_ref(source), "query": context.query, "scope": evidence_scope_from_question(context.question)},
        output_key=context.config.default_output_key(context.tool_name),
        depends_on=[source],
    )


def _search_evidence(context: BuildContext) -> ToolCallSpec:
    """获取检索证据并返回。"""
    source = context.source or "resolved_candidate"
    profile_browse = context.intent == "candidate_profile_intro"
    return ToolCallSpec(
        name=context.tool_name,
        arguments={
            "query": "" if profile_browse else context.query,
            "candidate_ids": _candidate_ids_ref(source),
            "scope": "both" if profile_browse else evidence_scope_from_question(context.question),
        },
        output_key=context.config.default_output_key(context.tool_name),
        depends_on=[source],
    )


def _candidate_ids_ref(source: str) -> dict[str, Any]:
    """按候选来源类型生成 candidate_ids 引用。"""
    if source.startswith("resolved_candidate"):
        return structured_arg_ref(source, ["candidate_ids"])
    return structured_arg_ref(source, ["resume_identity"], mapped=True)


def _single_candidate_ref(source: str) -> dict[str, Any]:
    """按候选来源类型生成单个候选人引用。"""
    if source.startswith("resolved_candidate"):
        return structured_arg_ref(source, ["candidate_ids", "0"])
    return structured_arg_ref(source, ["resume_identity", "0"])


def _comparison_pack(context: BuildContext) -> ToolCallSpec:
    """获取比较数据包并返回。"""
    source = context.source or "resolved_candidates"
    arguments: dict[str, Any] = {"candidate_ids": _candidate_ids_ref(source)}
    domain = domain_scope_key(context.router_output)
    if domain:
        arguments["domain"] = domain
    if context.query:
        arguments["query"] = context.query
    return ToolCallSpec(name=context.tool_name, arguments=arguments, depends_on=[source])


def _criteria_source(context: BuildContext) -> ToolCallSpec:
    """获取评分标准来源并返回。"""
    arguments: dict[str, Any] = {}
    if context.intent in {"candidate_ranking", "jd_scoring"} and context.tool_name == "load_default_jd_criteria":
        target = ranking_target_text(context.question, context.router_output)
        if not target:
            return ToolCallSpec(
                name=context.config.first_tool_with_role("general_ranking_criteria"),
                output_key=context.config.default_output_key(context.config.first_tool_with_role("general_ranking_criteria")),
            )
        if target:
            arguments["target_role"] = target
    return ToolCallSpec(name=context.tool_name, arguments=arguments, output_key=context.config.default_output_key(context.tool_name))


def _extract_criteria(context: BuildContext) -> ToolCallSpec:
    """提取评分标准并返回。"""
    return ToolCallSpec(
        name=context.tool_name,
        arguments={"jd_text": context.question},
        output_key=context.config.default_output_key(context.tool_name),
    )


def _score_collection(context: BuildContext) -> ToolCallSpec:
    """构建候选人集合评分调用并返回。"""
    source = context.source or "candidate_pool"
    criteria = context.criteria or "criteria"
    candidate_ids = (
        structured_arg_ref(source, ["candidate_ids"])
        if source.startswith("resolved_candidate")
        else structured_arg_ref(source, ["resume_identity"], mapped=True)
    )
    return ToolCallSpec(
        name=context.tool_name,
        arguments={"candidate_ids": candidate_ids, "criteria": structured_arg_ref(criteria)},
        output_key="scores",
        depends_on=[source, criteria],
    )


def _rank_scores(context: BuildContext) -> ToolCallSpec:
    """排序评分集合并返回。"""
    scores = context.scores or "scores"
    return ToolCallSpec(
        name=context.tool_name,
        arguments={"scored_candidates": structured_arg_ref(scores)},
        depends_on=[scores],
    )


_BUILDERS: dict[str, Builder] = {
    "list_candidates": _list_candidates,
    "structured_filter": _structured_filter,
    "semantic_search": _semantic_search,
    "resolve_reference": _resolve_reference,
    "count_collection": _count_collection,
    "single_profile": _single_profile,
    "multi_profile": _multi_profile,
    "single_evidence": _single_evidence,
    "search_evidence": _search_evidence,
    "comparison_pack": _comparison_pack,
    "criteria_source": _criteria_source,
    "extract_criteria": _extract_criteria,
    "score_collection": _score_collection,
    "rank_scores": _rank_scores,
}
