"""Execution policy node entrypoint.

这个文件负责什么：
- graph 层入口，调用规则层生成 ExecutionDecision。
- 把 ExecutionDecision 映射成 graph 条件边：template / generic。

应该从哪个函数读起：
- resolve_execution_policy
- route_after_execution_policy

不会负责什么：
- 不重新判断 intent/scenario。
- 不生成 SemanticPlan / QueryPlan。
- 不拼工具参数、不调用 tools。
"""

from __future__ import annotations

from typing import Literal

from resume_query_ai_qa.core.config import ResumeQAConfig
from resume_query_ai_qa.core.rules.execution_policy_rules import resolve_execution_decision
from resume_query_ai_qa.core.schemas import ExecutionDecision, RouterOutput


def resolve_execution_policy(
    question: str,
    router_output: RouterOutput,
    config: ResumeQAConfig,
) -> ExecutionDecision:
    """返回执行图使用的明确调度决策。

    输入是 condition_normalizer 之后的 RouterOutput；本函数只委托规则层，
    不在 graph node 里散落 workflow 匹配逻辑。
    """
    return resolve_execution_decision(question, router_output, config)


def route_after_execution_policy(decision: ExecutionDecision) -> Literal["template", "generic"]:
    """将执行决策映射为执行图边标签。

    workflow_template 直接进 plan_compiler；generic_tool_binding 先进入 planner。
    """
    return "template" if decision.compiler == "workflow_template" else "generic"
