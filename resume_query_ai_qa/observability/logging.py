"""Loguru-backed structured logging for Query-AI runs."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from loguru import logger

from resume_query_ai_qa.core.config import ResumeQAConfig
from resume_query_ai_qa.core.schemas import ResumeQAState

_CONFIGURED_SINKS: set[str] = set()
_DEFAULT_SINK_REMOVED = False


def configure_query_ai_logging(config: ResumeQAConfig) -> None:
    """按应用配置初始化结构化日志输出；同一日志文件只注册一次。"""
    global _DEFAULT_SINK_REMOVED
    logs_dir = config.app_root / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    sink = str(logs_dir / "query_ai_events.jsonl")
    if sink in _CONFIGURED_SINKS:
        return
    if not _DEFAULT_SINK_REMOVED:
        logger.remove()
        _DEFAULT_SINK_REMOVED = True
    logger.add(
        sink,
        serialize=True,
        rotation="20 MB",
        retention="14 days",
        enqueue=True,
        backtrace=False,
        diagnose=False,
        level="INFO",
    )
    _CONFIGURED_SINKS.add(sink)


def emit_event(kind: str, *, config: ResumeQAConfig | None = None, **fields: Any) -> None:
    """清洗字段并发送结构化事件，不改变查询业务状态。"""
    if config is not None:
        configure_query_ai_logging(config)
    payload = _safe_payload(fields)
    payload.setdefault("event_type", kind)
    logger.bind(**payload).info(kind)


def write_run_log(qa: ResumeQAState, config: ResumeQAConfig) -> None:
    """持久化一次查询的摘要和诊断明细；深度调试信息按 trace 开关写入。"""
    configure_query_ai_logging(config)
    logs_dir = config.app_root / "logs"
    created_at = datetime.now(timezone.utc).isoformat()
    trace_id = qa.trace.trace_id or uuid.uuid4().hex
    summary = _compact_run_summary(qa, created_at, trace_id)
    qa.trace.run_summary = summary
    detail = {
        "run_summary": summary,
        "decision_log": qa.trace.decision_log,
        "route_events": qa.trace.route_events,
        "failed_at": _failed_at(qa),
        "final_answer": _compact_final_answer(qa),
        "context_delta": _context_delta(qa.session_context, qa.updated_session_context),
    }
    if qa.trace.deep_debug:
        detail["node_events"] = qa.trace.node_events
        detail["state_snapshots"] = qa.trace.state_snapshots
    with (logs_dir / "qa_runs.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(summary, ensure_ascii=False, default=str) + "\n")
    (logs_dir / f"{created_at.replace(':', '-').replace('+', '_')}_{trace_id}.json").write_text(
        json.dumps(detail, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


def _compact_run_summary(qa: ResumeQAState, created_at: str, trace_id: str) -> dict[str, Any]:
    """压缩运行状态为适合检索的摘要，不包含完整工具结果。"""
    return {
        "created_at": created_at,
        "trace_id": trace_id,
        "question": qa.question,
        "intent": qa.intent,
        "final_status": qa.trace.final_status,
        "clarification_required": qa.clarification_required,
        "engines_by_node": {
            str(item.get("node")): str(item.get("engine") or "")
            for item in qa.trace.decision_log
            if item.get("node")
        },
        "tool_result_status": _tool_result_status(qa),
        "validation_errors_count": {
            "plan": len(qa.trace.plan_validation_errors),
            "execution": len(qa.trace.execution_validation_errors),
            "answer": len(qa.trace.answer_validation_errors),
        },
        "path_preview": _path_preview(qa),
        "failed_at_node": _failed_at(qa).get("node", ""),
        "failed_reason": _failed_at(qa).get("reason", ""),
        "answer_preview": (_preview(qa.answer.answer, 300) if qa.answer else ""),
    }


def _execution_path(qa: ResumeQAState) -> list[dict[str, Any]]:
    """获取执行路径并返回。"""
    events: list[dict[str, Any]] = []
    for item in qa.trace.decision_log:
        node = str(item.get("node") or "")
        output = item.get("output") if isinstance(item.get("output"), dict) else {}
        events.append(
            _strip_empty(
                {
                    "kind": "node",
                    "step": item.get("step"),
                    "created_at": item.get("created_at", ""),
                    "node": node,
                    "engine": item.get("engine", ""),
                    "duration_ms": item.get("duration_ms"),
                    "fallback_reason": item.get("fallback_reason", ""),
                    "status": output.get("status") or ("ok" if output.get("ok") is True else "failed" if output.get("ok") is False else ""),
                    "errors": output.get("errors", []),
                    "warnings": output.get("warnings", []),
                    "summary": _node_summary(node, output),
                }
            )
        )
    for item in qa.trace.route_events:
        events.append(
            _strip_empty(
                {
                    "kind": "route",
                    "step": item.get("step"),
                    "created_at": item.get("created_at", ""),
                    "route_from": item.get("route_from", ""),
                    "route_to": item.get("route_to", ""),
                    "reason": item.get("reason", ""),
                    "retry_count": item.get("retry_count"),
                    "errors": item.get("errors", []),
                }
            )
        )
    return sorted(events, key=_execution_path_sort_key)


def _execution_path_sort_key(item: dict[str, Any]) -> tuple[str, int, int]:
    """生成执行路径排序键，保证同一时刻节点事件排在路由事件之前。"""
    created_at = str(item.get("created_at") or "")
    kind_order = 0 if item.get("kind") == "node" else 1
    return (created_at, kind_order, int(item.get("step") or 0))


def _node_timeline(qa: ResumeQAState) -> list[dict[str, Any]]:
    """提取节点时间线所需的最小诊断字段。"""
    rows: list[dict[str, Any]] = []
    for item in qa.trace.decision_log:
        output = item.get("output") if isinstance(item.get("output"), dict) else {}
        rows.append(
            _strip_empty(
                {
                    "step": item.get("step"),
                    "node": item.get("node", ""),
                    "engine": item.get("engine", ""),
                    "duration_ms": item.get("duration_ms"),
                    "fallback_reason": item.get("fallback_reason", ""),
                    "errors": output.get("errors", []),
                    "warnings": output.get("warnings", []),
                    "repair_action": output.get("repair_action", ""),
                    "error_category": output.get("error_category", ""),
                }
            )
        )
    return rows


def _failed_at(qa: ResumeQAState) -> dict[str, Any]:
    """从最终节点和路由事件中定位失败位置与原因。"""
    if qa.trace.final_status not in {"failed", "needs_clarification"}:
        return {}
    last_route = qa.trace.route_events[-1] if qa.trace.route_events else {}
    last_node = qa.trace.decision_log[-1] if qa.trace.decision_log else {}
    output = last_node.get("output") if isinstance(last_node.get("output"), dict) else {}
    errors = output.get("errors") or last_route.get("errors") or qa.answer_errors or qa.execution_errors or qa.plan_errors
    return _strip_empty(
        {
            "node": last_node.get("node", ""),
            "route_from": last_route.get("route_from", ""),
            "route_to": last_route.get("route_to", ""),
            "reason": last_route.get("reason") or output.get("status", ""),
            "errors": errors,
        }
    )


def _path_preview(qa: ResumeQAState) -> str:
    """获取路径预览并返回。"""
    nodes = [str(item.get("node") or "") for item in qa.trace.decision_log if item.get("node")]
    return " -> ".join(nodes)


def _compact_node_steps(qa: ResumeQAState) -> list[dict[str, Any]]:
    """把完整决策日志压缩为可展示的节点步骤列表。"""
    return [_compact_node_step(qa, item) for item in qa.trace.decision_log]


def _compact_node_step(qa: ResumeQAState, item: dict[str, Any]) -> dict[str, Any]:
    """压缩单个节点决策，同时保留关键摘要和诊断详情。"""
    node = str(item.get("node") or "")
    output = item.get("output") if isinstance(item.get("output"), dict) else {}
    return {
        "step": item.get("step"),
        "node": node,
        "engine": item.get("engine", ""),
        "duration_ms": item.get("duration_ms"),
        "fallback_reason": item.get("fallback_reason", ""),
        "summary": _node_summary(node, output),
        "details": _node_details(qa, node, output),
    }


def _node_summary(node: str, output: dict[str, Any]) -> str:
    """按节点类型生成短摘要，供运行日志快速浏览。"""
    if node == "router":
        intent = output.get("intent") or "-"
        sub_intents = output.get("sub_intent_candidates") or []
        return f"intent={intent}; sub_intents={sub_intents}" if sub_intents else f"intent={intent}"
    if node == "condition_normalizer":
        return f"normalized_conditions={len(output.get('normalized_conditions') or [])}"
    if node == "planner":
        plan = output.get("semantic_plan") or {}
        return f"semantic_intent={plan.get('intent') or '-'}; steps={len(plan.get('steps') or [])}"
    if node == "plan_compiler":
        tools = output.get("compiled_tools") or []
        return f"{output.get('strategy') or '-'}; tools={len(tools)}"
    if node == "executor":
        return f"tools={len(output.get('tool_results_summary') or [])}"
    if node in {"plan_validator", "execution_validator", "answer_validator"}:
        return "ok" if output.get("ok") else f"errors={len(output.get('errors') or [])}"
    if node in {"aggregator", "answer_rewrite", "rule_answer_fallback"}:
        return f"claims={output.get('claim_count', 0)}; evidence={output.get('used_evidence_count', 0)}"
    if node == "final":
        return f"status={output.get('status') or '-'}"
    if node == "clarification":
        return "needs_clarification"
    if node == "fail":
        return "failed"
    return node or "unknown"


def _node_details(qa: ResumeQAState, node: str, output: dict[str, Any]) -> dict[str, Any]:
    """按节点类型提取诊断详情，并移除空字段。"""
    if node == "final":
        delta = _context_delta(qa.session_context, qa.updated_session_context)
        return {
            "status": output.get("status"),
            "context_before_keys": sorted((qa.session_context or {}).keys()),
            "context_after_keys": sorted((qa.updated_session_context or {}).keys()),
            "context_delta_keys": sorted(delta.keys()),
        }
    if node == "executor":
        return {"tools": _executor_tool_details(qa)}
    return _strip_empty(output)


def _executor_tool_details(qa: ResumeQAState) -> list[dict[str, Any]]:
    """将工具执行工具详情投影为可观测数据；只做脱敏、压缩或持久化，不改变业务状态。"""
    calls = _iter_plan_calls(qa.plan) if qa.plan else []
    output: list[dict[str, Any]] = []
    for index, result in enumerate(qa.tool_results):
        call = calls[index] if index < len(calls) else None
        output.append(
            _strip_empty(
                {
                    "index": index,
                    "tool": result.tool_name,
                    "status": "ok" if result.ok else "failed",
                    "output_key": getattr(call, "output_key", "") if call is not None else "",
                    "result_shape": _result_shape(result.data),
                    "result_count": _result_count(result.data),
                    "error": result.error,
                    "warnings": result.warnings,
                }
            )
        )
    return output


def _tool_result_status(qa: ResumeQAState) -> list[dict[str, Any]]:
    """将工具结果状态投影为可观测数据；只做脱敏、压缩或持久化，不改变业务状态。"""
    return [
        _strip_empty(
            {
                "tool": result.tool_name,
                "status": "ok" if result.ok else "failed",
                "result_shape": _result_shape(result.data),
                "result_count": _result_count(result.data),
                "error": result.error,
            }
        )
        for result in qa.tool_results
    ]


def _result_shape(value: Any) -> str:
    """将结果结构形态投影为可观测数据；只做脱敏、压缩或持久化，不改变业务状态。"""
    if value is None:
        return "none"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "dict"
    if hasattr(value, "model_dump"):
        return value.__class__.__name__
    return type(value).__name__


def _result_count(value: Any) -> int | None:
    """将结果计数投影为可观测数据；只做脱敏、压缩或持久化，不改变业务状态。"""
    if isinstance(value, (list, dict)):
        return len(value)
    return None


def _compact_final_answer(qa: ResumeQAState) -> dict[str, Any]:
    """将压缩结果收口答案投影为可观测数据；只做脱敏、压缩或持久化，不改变业务状态。"""
    if not qa.answer:
        return {}
    answer_text = qa.answer.answer or ""
    return {
        "text": answer_text,
        "answer_length": len(answer_text),
        "claim_count": len(qa.answer.claims),
        "claim_types": [claim.claim_type for claim in qa.answer.claims],
        "used_evidence_count": len(qa.answer.used_evidence_refs),
        "warnings": qa.answer.warnings,
    }


def _context_delta(before: dict[str, Any] | None, after: dict[str, Any] | None) -> dict[str, Any]:
    """将上下文变化投影为可观测数据；只做脱敏、压缩或持久化，不改变业务状态。"""
    before = before or {}
    after = after or {}
    delta: dict[str, Any] = {}
    for key in sorted(after):
        if key not in before or not _json_equal(before.get(key), after.get(key)):
            delta[key] = after[key]
    return delta


def _json_equal(left: Any, right: Any) -> bool:
    """将json相等判断投影为可观测数据；只做脱敏、压缩或持久化，不改变业务状态。"""
    return json.dumps(left, ensure_ascii=False, sort_keys=True, default=str) == json.dumps(right, ensure_ascii=False, sort_keys=True, default=str)


def _iter_plan_calls(plan: Any) -> list[Any]:
    """将iter计划调用投影为可观测数据；只做脱敏、压缩或持久化，不改变业务状态。"""
    calls = list(plan.tool_calls)
    for sub_task in plan.sub_tasks:
        calls.extend(sub_task.tool_calls)
    return calls


def _preview(text: str, limit: int) -> str:
    """将预览投影为可观测数据；只做脱敏、压缩或持久化，不改变业务状态。"""
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def _safe_payload(fields: dict[str, Any]) -> dict[str, Any]:
    """将安全载荷载荷投影为可观测数据；只做脱敏、压缩或持久化，不改变业务状态。"""
    return json.loads(json.dumps(fields, ensure_ascii=False, default=str))


def _strip_empty(value: dict[str, Any]) -> dict[str, Any]:
    """移除字典中的空字段并返回。"""
    return {key: item for key, item in value.items() if item not in (None, "", [], {})}
