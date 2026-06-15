"""Conditional edge decisions for the Query-AI graph.

这个文件负责什么：
  根据 validator/policy 节点写回的 state 字段选择下一跳，并记录 route trace。

应该从哪个函数读起：
  route_after_execution_policy_node() -> route_after_plan_validation()
  -> route_after_execution_validation() -> route_after_answer_validation()。

不会负责什么：
  不重新理解问题，不修复 plan/result/answer；具体分类来自各 node 的 classify/policy。
"""

from __future__ import annotations

from resume_query_ai_qa.nodes.execution_policy import route_after_execution_policy
from resume_query_ai_qa.nodes.execution_repair import classify_execution_repair_action
from resume_query_ai_qa.nodes.plan_repair import classify_plan_repair_action
from resume_query_ai_qa.state import record_route_decision

from .state import _GraphState
from .utils import require_plan


def route_after_execution_policy_node(state: _GraphState) -> str:
    """根据 ExecutionDecision.compiler 选择 template 或 generic 路径。"""
    route = route_after_execution_policy(state["execution_decision"])
    record_route_decision(
        state["qa"],
        route_from="execution_policy",
        route_to=route,
        reason=state["execution_decision"].reason,
        config=state["config"],
    )
    return route


def route_after_plan_validation(state: _GraphState) -> str:
    """根据 plan_validation_ok、plan repair 分类和重试次数选择下一跳。"""
    if state.get("plan_validation_ok"):
        record_route_decision(state["qa"], route_from="plan_validator", route_to="execute", reason="plan_validation_ok", config=state["config"])
        return "execute"
    decision = classify_plan_repair_action(
        state.get("current_plan_errors", []),
        state["qa"].plan,
        state["router_output"],
        config=state["config"],
        validation_issues=state.get("current_plan_issues", []),
    )
    if decision["action"] == "clarify":
        record_route_decision(state["qa"], route_from="plan_validator", route_to="clarify", reason=decision["reason"], errors=state.get("current_plan_errors", []), retry_count=int(state.get("plan_repairs", 0)), config=state["config"])
        return "clarify"
    if decision["action"] == "fail":
        record_route_decision(state["qa"], route_from="plan_validator", route_to="fail", reason=decision["reason"], errors=state.get("current_plan_errors", []), retry_count=int(state.get("plan_repairs", 0)), config=state["config"])
        return "fail"
    if int(state.get("plan_repairs", 0)) < int(state.get("max_plan_repairs", 0)):
        record_route_decision(state["qa"], route_from="plan_validator", route_to="repair", reason=decision["reason"], errors=state.get("current_plan_errors", []), retry_count=int(state.get("plan_repairs", 0)), config=state["config"])
        return "repair"
    record_route_decision(state["qa"], route_from="plan_validator", route_to="fail", reason="plan_repair_limit_exceeded", errors=state.get("current_plan_errors", []), retry_count=int(state.get("plan_repairs", 0)), config=state["config"])
    return "fail"


def route_after_execution_validation(state: _GraphState) -> str:
    """根据 execution_validation_ok、execution repair 分类和重试次数选择下一跳。"""
    if state.get("execution_validation_ok"):
        record_route_decision(state["qa"], route_from="execution_validator", route_to="aggregate", reason="execution_validation_ok", config=state["config"])
        return "aggregate"
    decision = classify_execution_repair_action(
        state.get("current_execution_errors", []),
        state["qa"].tool_results,
        require_plan(state["qa"]),
        state["router_output"],
        config=state["config"],
        validation_issues=state.get("current_execution_issues", []),
    )
    if decision["action"] == "clarify":
        record_route_decision(state["qa"], route_from="execution_validator", route_to="clarify", reason=decision["reason"], errors=state.get("current_execution_errors", []), retry_count=int(state.get("execution_repairs", 0)), config=state["config"])
        return "clarify"
    if decision["action"] == "fail":
        record_route_decision(state["qa"], route_from="execution_validator", route_to="fail", reason=decision["reason"], errors=state.get("current_execution_errors", []), retry_count=int(state.get("execution_repairs", 0)), config=state["config"])
        return "fail"
    if int(state.get("execution_repairs", 0)) < int(state.get("max_execution_repairs", 0)):
        record_route_decision(state["qa"], route_from="execution_validator", route_to="repair", reason=decision["reason"], errors=state.get("current_execution_errors", []), retry_count=int(state.get("execution_repairs", 0)), config=state["config"])
        return "repair"
    record_route_decision(state["qa"], route_from="execution_validator", route_to="fail", reason="execution_repair_limit_exceeded", errors=state.get("current_execution_errors", []), retry_count=int(state.get("execution_repairs", 0)), config=state["config"])
    return "fail"


def route_after_answer_validation(state: _GraphState) -> str:
    """根据 answer_validation_ok、fallback flag 和 rewrite 次数选择下一跳。"""
    if state.get("answer_validation_ok"):
        record_route_decision(state["qa"], route_from="answer_validator", route_to="final", reason="answer_validation_ok", config=state["config"])
        return "final"
    if state.get("answer_fallback_requested"):
        record_route_decision(state["qa"], route_from="answer_validator", route_to="fallback", reason="answer_fallback_requested", errors=state.get("current_answer_errors", []), retry_count=int(state.get("answer_rewrites", 0)), config=state["config"])
        return "fallback"
    rewrites = int(state.get("answer_rewrites", 0))
    if rewrites < int(state.get("max_answer_rewrites", 0)):
        record_route_decision(state["qa"], route_from="answer_validator", route_to="rewrite", reason="answer_validation_error", errors=state.get("current_answer_errors", []), retry_count=rewrites, config=state["config"])
        return "rewrite"
    if rewrites == int(state.get("max_answer_rewrites", 0)):
        record_route_decision(state["qa"], route_from="answer_validator", route_to="fallback", reason="answer_rewrite_limit_reached", errors=state.get("current_answer_errors", []), retry_count=rewrites, config=state["config"])
        return "fallback"
    record_route_decision(state["qa"], route_from="answer_validator", route_to="fail", reason="answer_fallback_failed", errors=state.get("current_answer_errors", []), retry_count=rewrites, config=state["config"])
    return "fail"
