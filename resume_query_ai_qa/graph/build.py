"""LangGraph wiring for Query-AI.

这个文件负责什么：
  注册 graph 节点、普通边和条件边。

应该从哪个函数读起：
  build_state_graph()。

不会负责什么：
  不做 intent、plan、execution、answer 的业务判断；条件判断函数在 routes.py。
"""

from __future__ import annotations

import warnings

warnings.filterwarnings("ignore", category=PendingDeprecationWarning, module=r"langgraph\..*")

from langgraph.graph import END, START, StateGraph

from .nodes import (
    aggregator_node,
    answer_rewrite_node,
    answer_validator_node,
    clarification_node,
    condition_normalizer_node,
    execution_policy_node,
    execution_repair_node,
    execution_validator_node,
    executor_node,
    fail_node,
    final_node,
    plan_compiler_node,
    plan_repair_node,
    plan_validator_node,
    planner_node,
    router_node,
    rule_answer_fallback_node,
)
from .routes import (
    route_after_answer_validation,
    route_after_execution_policy_node,
    route_after_execution_validation,
    route_after_plan_validation,
)
from .state import _GraphState


def build_state_graph():
    """注册节点和边，并返回可执行 LangGraph；这里只描述拓扑，不承载业务规则。"""
    builder = StateGraph(_GraphState)
    builder.add_node("router", router_node)
    builder.add_node("condition_normalizer", condition_normalizer_node)
    builder.add_node("execution_policy", execution_policy_node)
    builder.add_node("planner", planner_node)
    builder.add_node("plan_compiler", plan_compiler_node)
    builder.add_node("plan_validator", plan_validator_node)
    builder.add_node("plan_repair", plan_repair_node)
    builder.add_node("executor", executor_node)
    builder.add_node("execution_validator", execution_validator_node)
    builder.add_node("execution_repair", execution_repair_node)
    builder.add_node("aggregator", aggregator_node)
    builder.add_node("answer_validator", answer_validator_node)
    builder.add_node("answer_rewrite", answer_rewrite_node)
    builder.add_node("rule_answer_fallback", rule_answer_fallback_node)
    builder.add_node("clarification", clarification_node)
    builder.add_node("fail", fail_node)
    builder.add_node("final", final_node)

    builder.add_edge(START, "router")
    builder.add_edge("router", "condition_normalizer")
    builder.add_edge("condition_normalizer", "execution_policy")
    builder.add_conditional_edges("execution_policy", route_after_execution_policy_node, {"template": "plan_compiler", "generic": "planner"})
    builder.add_edge("planner", "plan_compiler")
    builder.add_edge("plan_compiler", "plan_validator")
    builder.add_conditional_edges("plan_validator", route_after_plan_validation, {"execute": "executor", "repair": "plan_repair", "clarify": "clarification", "fail": "fail"})
    builder.add_edge("plan_repair", "plan_validator")
    builder.add_edge("executor", "execution_validator")
    builder.add_conditional_edges("execution_validator", route_after_execution_validation, {"aggregate": "aggregator", "repair": "execution_repair", "clarify": "clarification", "fail": "fail"})
    builder.add_edge("execution_repair", "plan_validator")
    builder.add_edge("aggregator", "answer_validator")
    builder.add_conditional_edges("answer_validator", route_after_answer_validation, {"final": "final", "rewrite": "answer_rewrite", "fallback": "rule_answer_fallback", "fail": "fail"})
    builder.add_edge("answer_rewrite", "answer_validator")
    builder.add_edge("rule_answer_fallback", "answer_validator")
    builder.add_edge("final", END)
    builder.add_edge("clarification", END)
    builder.add_edge("fail", END)
    return builder.compile()
