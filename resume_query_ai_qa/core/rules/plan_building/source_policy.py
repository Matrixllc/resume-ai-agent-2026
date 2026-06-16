"""Candidate source reuse and scope policy for QueryPlan construction."""

from __future__ import annotations

from typing import Any

from resume_query_ai_qa.core.config import load_config
from resume_query_ai_qa.core.schemas import QueryPlan, RouterOutput, SubTaskPlan, ToolCallSpec

from .query_args import filter_args, ranking_filter_args
from .refs import replace_ref_root


def is_candidate_source_tool(tool_name: str) -> bool:
    """判断候选人来源工具是否成立并返回布尔值。"""
    return tool_name in set(load_config().tools_with_role("candidate_source"))


def plan_calls(plan: QueryPlan) -> list[ToolCallSpec]:
    """获取计划调用集合并返回。"""
    calls = list(plan.tool_calls)
    for sub_task in plan.sub_tasks:
        calls.extend(sub_task.tool_calls)
    return calls


def last_output_key(calls: list[ToolCallSpec], tool_names: set[str] | list[str]) -> str:
    """获取最近输出键并返回。"""
    names = set(tool_names)
    for call in reversed(calls):
        if call.name in names:
            return call.output_key or default_output_key(call.name)
    return ""


def default_output_key(tool_name: str) -> str:
    """获取默认输出键并返回。"""
    return load_config().default_output_key(tool_name)


def reuse_candidate_source_for_count_list(sub_tasks: list[SubTaskPlan]) -> list[SubTaskPlan]:
    """根据数量列表生成reuse候选人来源并返回。"""
    canonical: ToolCallSpec | None = None
    output: list[SubTaskPlan] = []
    for sub_task in sub_tasks:
        calls: list[ToolCallSpec] = []
        for call in sub_task.tool_calls:
            if is_candidate_source_tool(call.name):
                if canonical is None:
                    canonical = call
                    calls.append(call)
                elif source_signature(call) != source_signature(canonical):
                    calls.append(call)
                continue
            calls.append(call)
        output.append(sub_task.model_copy(update={
            "tool_calls": bind_current_calls_to_source(calls, canonical.output_key if canonical else "candidate_pool")
        }))
    return output


def bind_current_calls_to_source(calls: list[ToolCallSpec], output_key: str) -> list[ToolCallSpec]:
    """绑定当前调用集合TO来源并返回。"""
    return [replace_ref_root(call, "candidate_pool", output_key) for call in calls]


def bind_compound_consumers_to_canonical_source(plan: QueryPlan, router_output: RouterOutput | None) -> QueryPlan:
    """绑定复合任务消费者集合TO规范来源并返回。"""
    if not plan.sub_tasks:
        return plan
    required_scope = candidate_required_scope(router_output)
    canonical = _canonical_candidate_source(plan, required_scope)
    if canonical is None:
        return plan
    tasks: list[SubTaskPlan] = []
    seen = False
    canonical_signature = source_signature(canonical)
    first_task_has_source = bool(plan.sub_tasks and any(source_signature(call) == canonical_signature for call in plan.sub_tasks[0].tool_calls))
    for index, task in enumerate(plan.sub_tasks):
        calls: list[ToolCallSpec] = []
        if index == 0 and not first_task_has_source:
            calls.append(canonical)
            seen = True
        for call in task.tool_calls:
            if is_candidate_source_tool(call.name) and call.name != "resolve_candidate_reference":
                if source_signature(call) == canonical_signature and not seen:
                    seen = True
                    calls.append(call)
                elif not required_scope and source_signature(call) != canonical_signature:
                    calls.append(call)
                continue
            calls.append(replace_ref_root(call, "candidate_pool", canonical.output_key or "candidate_pool"))
        tasks.append(task.model_copy(update={"tool_calls": calls}))
    return plan.model_copy(update={"sub_tasks": tasks})


def _canonical_candidate_source(plan: QueryPlan, required_scope: dict[str, Any]) -> ToolCallSpec | None:
    """选择复合计划共享候选池来源。"""
    sources = [
        call
        for call in plan_calls(plan)
        if is_candidate_source_tool(call.name) and call.name != "resolve_candidate_reference"
    ]
    if required_scope:
        for call in sources:
            accepted = candidate_source_scope(call)
            if accepted and all(accepted.get(key) == value for key, value in required_scope.items()):
                return call
        return ToolCallSpec(name="filter_candidates", arguments=required_scope, output_key="candidate_pool")
    return sources[0] if sources else None


def source_signature(call: ToolCallSpec) -> str:
    """获取来源signature并返回。"""
    return f"{call.name}:{sorted(call.arguments.items(), key=lambda item: item[0])!r}"


def candidate_source_conflict(
    call: ToolCallSpec,
    existing: ToolCallSpec | None,
    router_output: RouterOutput | None,
) -> dict[str, Any] | None:
    """获取候选人来源conflict并返回。"""
    if call.name == "resolve_candidate_reference":
        return None
    required = candidate_required_scope(router_output)
    accepted = candidate_source_scope(call)
    if required and call.name == "list_all_candidates":
        return {"reason": "source_scope_conflict", "required_scope": required, "rejected_scope": accepted}
    if required and any(key in accepted and accepted.get(key) != value for key, value in required.items()):
        return {"reason": "source_scope_conflict", "required_scope": required, "rejected_scope": accepted}
    if existing is not None and source_signature(call) != source_signature(existing):
        return {"reason": "candidate_source_conflict", "accepted_source": existing.name, "rejected_source": call.name}
    return None


def candidate_required_scope(router_output: RouterOutput | None) -> dict[str, Any]:
    """获取候选人必需范围并返回。"""
    if router_output is None:
        return {}
    if router_output.intent in {"candidate_ranking", "jd_scoring"}:
        return ranking_filter_args("", router_output, None)
    return filter_args("", router_output, None)


def candidate_source_scope(call: ToolCallSpec) -> dict[str, Any]:
    """获取候选人来源范围并返回。"""
    return dict(call.arguments) if call.name in {"filter_candidates", "hybrid_search_candidates"} else {}


def dedupe_repeated_calls(calls: list[ToolCallSpec]) -> list[ToolCallSpec]:
    """去重重复项调用集合并返回。"""
    output: list[ToolCallSpec] = []
    seen: set[str] = set()
    for call in calls:
        signature = source_signature(call)
        if signature not in seen:
            output.append(call)
            seen.add(signature)
    return output
