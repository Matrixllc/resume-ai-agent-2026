from __future__ import annotations

from typing import Any

from resume_query_ai_qa.core.config import ResumeQAConfig
from resume_query_ai_qa.core.llm import llm_identity
from resume_query_ai_qa.core.schemas import AggregatedAnswer, QueryPlan, ResumeQAState, ToolResult
from resume_query_ai_qa.state import record_node_decision, record_state_snapshot

from .utils import iter_plan_calls, preview


def record_plan(qa: ResumeQAState, plan: QueryPlan) -> None:
    """为执行图记录计划；仅处理编排、状态投影或 trace，不承载业务判断。"""
    qa.plan = plan
    qa.sub_tasks = plan.sub_tasks
    qa.trace.planner_output = plan


def record_tool_results(qa: ResumeQAState, plan: QueryPlan, tool_results: list[ToolResult]) -> None:
    """为执行图记录工具结果；仅处理编排、状态投影或 trace，不承载业务判断。"""
    qa.tool_results = tool_results
    qa.trace.tool_calls = list(plan.tool_calls)
    for sub_task in plan.sub_tasks:
        qa.trace.tool_calls.extend(sub_task.tool_calls)
    qa.trace.tool_results_summary = [f"{item.tool_name}:{'ok' if item.ok else item.error}" for item in tool_results]


def log_decision(
    qa: ResumeQAState,
    *,
    node: str,
    engine: str,
    output: dict[str, Any],
    summary: str = "",
    debug: dict[str, Any] | None = None,
    fallback_reason: str = "",
    duration_ms: float | None = None,
    llm: dict[str, Any] | None = None,
) -> None:
    """为执行图日志决策；仅处理编排、状态投影或 trace，不承载业务判断。"""
    record_node_decision(
        qa,
        node=node,
        engine=engine,
        output=output,
        summary=summary,
        debug=debug,
        fallback_reason=fallback_reason,
        duration_ms=duration_ms,
        llm=llm,
    )
    if qa.trace.deep_debug:
        record_state_snapshot(qa, label=f"after_{node}")


def decision_meta(node: str, engine: str, fallback_reason: str = "", config: ResumeQAConfig | None = None) -> dict[str, Any]:
    """为执行图决策元信息；仅处理编排、状态投影或 trace，不承载业务判断。"""
    meta: dict[str, Any] = {"node": node, "engine": engine, "fallback_reason": fallback_reason}
    if config is not None and engine in {"llm", "rule_fallback"}:
        meta["llm"] = llm_identity(config)
    return meta


def plan_summary(plan: QueryPlan) -> dict[str, Any]:
    """为执行图计划摘要；仅处理编排、状态投影或 trace，不承载业务判断。"""
    return {
        "intent": plan.intent,
        "is_compound": plan.is_compound,
        "sub_tasks": [sub_task.intent for sub_task in plan.sub_tasks],
        "tool_calls": [call.model_dump() for call in iter_plan_calls(plan)],
        "notes": plan.notes,
    }


def ref_bindings_from_plan(plan: QueryPlan) -> list[dict[str, Any]]:
    """从计划中提取引用绑定并返回。"""
    bindings: list[dict[str, Any]] = []
    for call in iter_plan_calls(plan):
        for name, value in (call.arguments or {}).items():
            refs = _structured_refs(value)
            for ref in refs:
                bindings.append({"tool": call.name, "argument": name, **ref})
    return bindings


def answer_summary(answer: AggregatedAnswer) -> dict[str, Any]:
    """为执行图答案摘要；仅处理编排、状态投影或 trace，不承载业务判断。"""
    preview_limit = 240
    answer_text = answer.answer or ""
    return {
        "answer_preview": preview(answer_text, preview_limit),
        "answer_length": len(answer_text),
        "answer_truncated": len(answer_text) > preview_limit,
        "claim_count": len(answer.claims),
        "claim_types": [claim.claim_type for claim in answer.claims],
        "used_evidence_count": len(answer.used_evidence_refs),
        "warnings": answer.warnings,
    }


def aggregator_io_log(meta: dict[str, Any]) -> dict[str, Any]:
    """为执行图答案聚合io日志；仅处理编排、状态投影或 trace，不承载业务判断。"""
    payload = meta.get("aggregator_io")
    if not isinstance(payload, dict):
        return {}
    return {"aggregator_io_mode": payload.get("mode", "")}


def aggregator_io_debug(meta: dict[str, Any]) -> dict[str, Any]:
    """为执行图答案聚合iodebug；仅处理编排、状态投影或 trace，不承载业务判断。"""
    payload = meta.get("aggregator_io")
    if not isinstance(payload, dict):
        return {}
    return {
        "aggregator_input_prompt": payload.get("prompt", ""),
        "aggregator_response": payload.get("response", {}),
    }


def aggregator_layout_log(meta: dict[str, Any]) -> dict[str, Any]:
    """为执行图答案聚合布局日志；仅处理编排、状态投影或 trace，不承载业务判断。"""
    layout = str(meta.get("answer_layout") or "").strip()
    if not layout:
        return {}
    return {
        "answer_layout": layout,
        "answer_layout_source": meta.get("answer_layout_source", ""),
        "answer_layout_rules": meta.get("answer_layout_rules", []),
    }


def aggregator_domain_log(meta: dict[str, Any]) -> dict[str, Any]:
    """为执行图答案聚合领域日志；仅处理编排、状态投影或 trace，不承载业务判断。"""
    keys = [
        "task_type",
        "freedom_level",
        "slots",
        "task_match_reason",
        "layout_match_reason",
        "context_summary",
        "llm_mode",
        "drift_rejection_reason",
        "insufficient_info_reasons",
    ]
    return {key: meta.get(key) for key in keys if meta.get(key) not in (None, "", [], {})}


def _structured_refs(value: Any) -> list[dict[str, Any]]:
    """为执行图structured引用；仅处理编排、状态投影或 trace，不承载业务判断。"""
    refs: list[dict[str, Any]] = []
    if isinstance(value, dict):
        if "$ref" in value:
            refs.append({"ref": value.get("$ref", ""), "path": value.get("path", []), "map": bool(value.get("map", False))})
            return refs
        for item in value.values():
            refs.extend(_structured_refs(item))
    elif isinstance(value, list):
        for item in value:
            refs.extend(_structured_refs(item))
    return refs
