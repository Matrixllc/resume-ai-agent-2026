"""State-owned trace event helpers backed by Loguru observability."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from resume_query_ai_qa.core.config import ResumeQAConfig
from resume_query_ai_qa.core.schemas import ResumeQAState
from resume_query_ai_qa.observability import emit_event


def record_run_start(qa: ResumeQAState, config: ResumeQAConfig) -> None:
    """记录一次查询运行的起点和初始上下文键。"""
    event = {
        "trace_id": qa.trace.trace_id,
        "event_type": "run_start",
        "question": qa.question,
        "session_context_keys": sorted((qa.session_context or {}).keys()),
        "created_at": _now(),
    }
    emit_event("run_start", config=config, **event)


def record_node_decision(
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
    config: ResumeQAConfig | None = None,
) -> None:
    """记录节点决策、耗时和摘要；深度调试开启时额外保存输入输出事件。"""
    step = len(qa.trace.decision_log) + 1
    base = {
        "trace_id": qa.trace.trace_id,
        "step": step,
        "node": node,
        "engine": engine,
        "fallback_reason": fallback_reason,
    }
    start_event = {**base, "event_type": "node_start", "created_at": _now(), "input_summary": _input_summary(qa, node)}
    end_event = {
        **base,
        "event_type": "node_end",
        "created_at": _now(),
        "duration_ms": round(duration_ms, 2) if duration_ms is not None else None,
        "output_summary": _output_summary(output),
        "errors": output.get("errors", []) if isinstance(output, dict) else [],
        "warnings": output.get("warnings", []) if isinstance(output, dict) else [],
    }
    item: dict[str, Any] = {
        "step": step,
        "node": node,
        "engine": engine,
        "fallback_reason": fallback_reason,
        "created_at": end_event["created_at"],
        "summary": summary or _node_summary(node, output),
        "output": output,
    }
    if qa.trace.deep_debug and debug:
        item["debug"] = debug
    if llm:
        item["llm"] = llm
        end_event["llm"] = llm
    if duration_ms is not None:
        item["duration_ms"] = round(duration_ms, 2)
    qa.trace.decision_log.append(item)
    if qa.trace.deep_debug:
        qa.trace.node_events.extend([start_event, end_event])
        emit_event("node_start", config=config, **start_event)
    else:
        qa.trace.node_events.append(end_event)
    emit_event("node_end", config=config, **end_event)


def record_route_decision(
    qa: ResumeQAState,
    *,
    route_from: str,
    route_to: str,
    reason: str = "",
    errors: list[str] | None = None,
    retry_count: int | None = None,
    config: ResumeQAConfig | None = None,
) -> None:
    """记录节点间路由选择；修复、兜底和失败分支会额外发送事件。"""
    event = {
        "trace_id": qa.trace.trace_id,
        "event_type": "route_decision",
        "step": len(qa.trace.route_events) + 1,
        "route_from": route_from,
        "route_to": route_to,
        "reason": reason,
        "errors": list(errors or []),
        "retry_count": retry_count,
        "created_at": _now(),
    }
    qa.trace.route_events.append(event)
    if route_to in {"repair", "fallback", "clarify", "fail"}:
        emit_event("route_decision", config=config, **event)


def record_state_snapshot(
    qa: ResumeQAState,
    *,
    label: str,
    config: ResumeQAConfig | None = None,
) -> None:
    """记录轻量状态快照，用于定位计划、结果或答案在哪一阶段发生变化。"""
    event = {
        "trace_id": qa.trace.trace_id,
        "event_type": "state_snapshot",
        "step": len(qa.trace.state_snapshots) + 1,
        "label": label,
        "created_at": _now(),
        "summary": {
            "intent": qa.intent,
            "has_plan": qa.plan is not None,
            "tool_results": len(qa.tool_results),
            "has_answer": qa.answer is not None,
            "plan_errors": len(qa.plan_errors),
            "execution_errors": len(qa.execution_errors),
            "answer_errors": len(qa.answer_errors),
            "clarification_required": qa.clarification_required,
        },
    }
    qa.trace.state_snapshots.append(event)
    emit_event("state_snapshot", config=config, **event)


def finalize_run_trace(qa: ResumeQAState, *, config: ResumeQAConfig | None = None) -> None:
    """汇总运行 trace 并发送结束事件，不重新判断业务规则。"""
    summary = {
        "trace_id": qa.trace.trace_id,
        "event_type": "run_end",
        "final_status": qa.trace.final_status,
        "node_count": len(qa.trace.decision_log),
        "route_count": len(qa.trace.route_events),
        "state_snapshot_count": len(qa.trace.state_snapshots),
        "created_at": _now(),
    }
    qa.trace.run_summary = {**qa.trace.run_summary, **summary}
    emit_event("run_end", config=config, **summary)


def record_run_error(qa: ResumeQAState, error: Exception, *, config: ResumeQAConfig | None = None) -> None:
    """记录未被业务流程吸收的运行异常。"""
    emit_event(
        "run_error",
        config=config,
        trace_id=qa.trace.trace_id,
        error_type=type(error).__name__,
        error=str(error),
        created_at=_now(),
    )


def _input_summary(qa: ResumeQAState, node: str) -> dict[str, Any]:
    """提取节点开始事件所需的轻量输入摘要。"""
    return {
        "node": node,
        "intent": qa.intent,
        "has_plan": qa.plan is not None,
        "tool_results": len(qa.tool_results),
        "has_answer": qa.answer is not None,
    }


def _output_summary(output: dict[str, Any]) -> dict[str, Any]:
    """从节点输出中筛选稳定且非空的诊断字段。"""
    keys = [
        "ok",
        "intent",
        "repair_action",
        "error_category",
        "answer_layout",
        "claim_count",
        "used_evidence_count",
        "fallback_requested",
        "status",
    ]
    return {key: output.get(key) for key in keys if isinstance(output, dict) and output.get(key) not in (None, "", [], {})}


def _node_summary(node: str, output: dict[str, Any]) -> str:
    """按节点类型生成人可读的决策摘要。"""
    if node == "router":
        sub_intents = output.get("sub_intent_candidates") or []
        return f"intent={output.get('intent') or '-'}" + (f"; sub_intents={sub_intents}" if sub_intents else "")
    if node == "condition_normalizer":
        return f"normalized_conditions={len(output.get('normalized_conditions') or [])}"
    if node == "execution_policy":
        return f"{output.get('compiler') or '-'}: {output.get('workflow_name') or output.get('reason') or '-'}"
    if node == "planner":
        plan = output.get("semantic_plan") or {}
        return f"semantic_intent={plan.get('intent') or '-'}; steps={len(plan.get('steps') or [])}"
    if node == "plan_compiler":
        tools = output.get("compiled_tools") or []
        strategy = output.get("strategy") or "-"
        return f"{strategy}: {' -> '.join(tools) if tools else 'no tools'}"
    if node == "executor":
        return f"tools={len(output.get('tool_results_summary') or output.get('tool_calls') or [])}"
    if node in {"plan_validator", "execution_validator", "answer_validator"}:
        return "ok" if output.get("ok") else f"errors={len(output.get('errors') or [])}"
    if node in {"aggregator", "answer_rewrite", "rule_answer_fallback"}:
        layout = output.get("answer_layout") or "-"
        return f"layout={layout}; claims={output.get('claim_count', 0)}; evidence={output.get('used_evidence_count', 0)}"
    if node == "final":
        return f"status={output.get('status') or '-'}"
    if node == "clarification":
        return "needs_clarification"
    if node == "fail":
        return "failed"
    return node or "unknown"


def _now() -> str:
    """返回带时区的 UTC 时间字符串，供 trace 事件统一排序。"""
    return datetime.now(timezone.utc).isoformat()
