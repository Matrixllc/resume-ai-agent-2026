"""Compatibility facade for graph node adapters.

这个文件负责什么：
  保持旧的 `resume_query_ai_qa.graph.nodes` 导入路径稳定，并把实际 adapter
  按阶段转发到 query/planning/execution/answer/terminal 模块。

应该从哪个函数读起：
  不从这里读具体实现；先读 query_nodes.py，再按 graph 顺序继续读。

不会负责什么：
  不承载业务逻辑，不再堆放所有 adapter 实现。
"""

from __future__ import annotations

from .answer_nodes import aggregator_node, answer_rewrite_node, answer_validator_node, rule_answer_fallback_node
from .execution_nodes import execution_repair_node, execution_validator_node, executor_node
from .planning_nodes import plan_compiler_node, plan_repair_node, plan_validator_node, planner_node
from .query_nodes import condition_normalizer_node, execution_policy_node, router_node
from .terminal_nodes import clarification_node, fail_node, final_node

__all__ = [
    "aggregator_node",
    "answer_rewrite_node",
    "answer_validator_node",
    "clarification_node",
    "condition_normalizer_node",
    "execution_policy_node",
    "execution_repair_node",
    "execution_validator_node",
    "executor_node",
    "fail_node",
    "final_node",
    "plan_compiler_node",
    "plan_repair_node",
    "plan_validator_node",
    "planner_node",
    "router_node",
    "rule_answer_fallback_node",
]
