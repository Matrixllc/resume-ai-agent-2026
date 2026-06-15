from __future__ import annotations

from typing import Any, Dict, List

from resume_query_ai_qa.core.schemas import ResumeQAState

from .qa_utils import _first_non_empty, _strip_empty


def _diagnosis_summary(state: ResumeQAState, *, include_lookup: bool = True) -> Dict[str, Any]:
    validation = {
        "plan": list(state.trace.plan_validation_errors or []),
        "execution": list(state.trace.execution_validation_errors or []),
        "answer": list(state.trace.answer_validation_errors or []),
    }
    failed_route = _last_route_to(state, {"fail", "clarify", "fallback", "repair"})
    failed_step = _last_problem_step(state)
    fallback_steps = [
        _strip_empty(
            {
                "node": item.get("node", ""),
                "fallback_reason": item.get("fallback_reason", ""),
                "repair_action": (item.get("output") or {}).get("repair_action", "") if isinstance(item.get("output"), dict) else "",
                "repair_reason": (item.get("output") or {}).get("repair_reason", "") if isinstance(item.get("output"), dict) else "",
                "error_category": (item.get("output") or {}).get("error_category", "") if isinstance(item.get("output"), dict) else "",
            }
        )
        for item in state.trace.decision_log
        if item.get("fallback_reason")
        or (isinstance(item.get("output"), dict) and ((item.get("output") or {}).get("repair_action") or (item.get("output") or {}).get("error_category")))
    ]
    tool_failures = [
        {"tool": result.tool_name, "error": result.error}
        for result in state.tool_results
        if not result.ok
    ]
    warnings = _collect_warnings(state)
    reason = _first_non_empty(
        (failed_route or {}).get("reason", ""),
        (failed_step or {}).get("reason", ""),
        validation["plan"][0] if validation["plan"] else "",
        validation["execution"][0] if validation["execution"] else "",
        validation["answer"][0] if validation["answer"] else "",
        tool_failures[0]["error"] if tool_failures else "",
    )
    status = state.trace.final_status or "failed"
    if status == "ok" and fallback_steps:
        level = "warning"
    elif status == "ok" and warnings:
        level = "info"
    elif status == "needs_clarification":
        level = "clarification"
    elif status == "failed":
        level = "error"
    else:
        level = "ok"
    return _strip_empty(
        {
            "level": level,
            "status": status,
            "headline": _diagnosis_headline(status, reason, fallback_steps, warnings),
            "impact": _diagnosis_impact(status, fallback_steps),
            "handling": _diagnosis_handling(status, fallback_steps),
            "suggested_check": _diagnosis_suggested_check((failed_step or {}).get("node", ""), validation, fallback_steps, warnings),
            "technical_code": reason,
            "failed_node": (failed_step or {}).get("node", ""),
            "failed_reason": reason,
            "route_from": (failed_route or {}).get("route_from", ""),
            "route_to": (failed_route or {}).get("route_to", ""),
            "route_reason": (failed_route or {}).get("reason", ""),
            "fallbacks": fallback_steps,
            "tool_failures": tool_failures,
            "warnings": warnings[:8],
            "validation_errors": {key: value for key, value in validation.items() if value},
            "trace_lookup": f"trace_id={state.trace.trace_id}; detail=resume_query_ai_qa/logs/*{state.trace.trace_id}*.json" if include_lookup and state.trace.trace_id else "",
        }
    )


def _last_route_to(state: ResumeQAState, route_targets: set[str]) -> Dict[str, Any]:
    for item in reversed(state.trace.route_events):
        if str(item.get("route_to") or "") in route_targets:
            return item
    return {}


def _last_problem_step(state: ResumeQAState) -> Dict[str, Any]:
    for item in reversed(state.trace.decision_log):
        output = item.get("output") if isinstance(item.get("output"), dict) else {}
        errors = output.get("errors") or []
        if output.get("ok") is False or errors or output.get("error_category"):
            return {
                "node": item.get("node", ""),
                "reason": output.get("error_category") or "; ".join(str(error) for error in errors[:2]),
            }
    return {}


def _collect_warnings(state: ResumeQAState) -> List[str]:
    warnings: List[str] = []
    if state.answer:
        warnings.extend(str(item) for item in state.answer.warnings if str(item).strip())
    for result in state.tool_results:
        warnings.extend(str(item) for item in result.warnings if str(item).strip())
    for item in state.trace.decision_log:
        output = item.get("output") if isinstance(item.get("output"), dict) else {}
        warnings.extend(str(item) for item in output.get("warnings", []) if str(item).strip())
    return list(dict.fromkeys(warnings))


def _diagnosis_headline(status: str, reason: str, fallback_steps: List[Dict[str, Any]], warnings: List[str]) -> str:
    if status == "failed":
        return f"失败：{reason or '查看 validation_errors 和 route_events'}"
    if status == "needs_clarification":
        return f"需要澄清：{reason or '缺少上下文或比较对象'}"
    if fallback_steps:
        return "已完成，但发生 fallback/repair，请查看 fallbacks。"
    if warnings:
        return "已完成，存在可解释 warning。"
    return "已完成，主链路未记录失败或 fallback。"


def _diagnosis_impact(status: str, fallback_steps: List[Dict[str, Any]]) -> str:
    if status in {"failed", "needs_clarification"}:
        return "本轮没有生成可作为最终结果使用的已校验答案。"
    if fallback_steps:
        return "最终答案已重新通过校验，中间异常输出未直接交付。"
    return "未发现影响最终答案可信度的问题。"


def _diagnosis_handling(status: str, fallback_steps: List[Dict[str, Any]]) -> str:
    if status in {"failed", "needs_clarification"}:
        return "系统停止链路并保留诊断，没有静默生成未经校验的答案。"
    if fallback_steps:
        return "系统丢弃或修复不可用的中间结果，并重新进入 validator。"
    return "系统按正常路径完成执行和校验。"


def _diagnosis_suggested_check(
    node: str,
    validation: Dict[str, List[str]],
    fallback_steps: List[Dict[str, Any]],
    warnings: List[str],
) -> str:
    target = node or str((fallback_steps[-1] if fallback_steps else {}).get("node") or "")
    if validation.get("answer") or target in {"aggregator", "answer_validator", "answer_rewrite", "rule_answer_fallback"}:
        return "检查 aggregator grounded context、answer layout、claims 和 answer validator。"
    if validation.get("execution") or target in {"executor", "execution_validator", "execution_repair"}:
        return "检查工具参数、工具结果、候选池 lineage 和 execution validator。"
    if warnings and all(str(item).startswith("answer_layout") for item in warnings):
        return "这是答案布局审计信息；如需调整展示，检查 answer_layouts.yaml。"
    if not target and not any(validation.values()):
        return "无需处理；可使用 trace_id 查看完整执行记录。"
    return "检查 Router intent/scenario、compiler template、tool policy 和 plan validator。"
