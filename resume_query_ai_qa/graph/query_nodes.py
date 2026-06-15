"""Graph adapters for query understanding stages.

这个文件负责什么：
  router、condition_normalizer、execution_policy 三个前置节点的 graph state
  读写和 trace 记录。

应该从哪个函数读起：
  router_node() -> condition_normalizer_node() -> execution_policy_node()。

不会负责什么：
  不实现 intent/condition/workflow 业务规则；这里只把 graph state 交给 nodes/*
  包，并记录输出。
"""

from __future__ import annotations

import time
from typing import Any

from resume_query_ai_qa.core.llm import is_llm_enabled
from resume_query_ai_qa.nodes.condition_normalizer import normalize_router_output
from resume_query_ai_qa.nodes.execution_policy import resolve_execution_policy
from resume_query_ai_qa.nodes.router import route_question, route_question_llm

from .state import _GraphState
from .trace_logging import decision_meta, log_decision
from .utils import elapsed_ms


def router_node(state: _GraphState) -> dict[str, Any]:
    """运行 router，写回 RouterOutput，并记录 intent/scenario/context 等摘要。"""
    qa = state["qa"]
    cfg = state["config"]
    started = time.perf_counter()
    if state["use_llm"] and is_llm_enabled(cfg):
        router_output = route_question_llm(qa.question, cfg)
        fallback_flags = [flag for flag in router_output.risk_flags if flag.startswith("llm_router_fallback")]
        meta = (
            decision_meta("router", "rule_fallback", "; ".join(flag.split(":", 1)[1] for flag in fallback_flags), cfg)
            if fallback_flags
            else decision_meta("router", "llm", config=cfg)
        )
    else:
        router_output = route_question(qa.question, cfg)
        meta = decision_meta("router", "rule")
    qa.intent = router_output.intent
    qa.trace.router_output = router_output
    log_decision(
        qa,
        node="router",
        engine=meta["engine"],
        fallback_reason=meta["fallback_reason"],
        llm=meta.get("llm"),
        output={
            "intent": router_output.intent,
            "is_compound": router_output.is_compound,
            "sub_intent_candidates": router_output.sub_intent_candidates,
            "sub_intent_evidence": [item.model_dump() for item in router_output.sub_intent_evidence],
            "scenario_decisions": {key: value.model_dump() for key, value in router_output.scenario_decisions.items()},
            "conditions": [item.model_dump() for item in router_output.conditions],
            "context_policy": router_output.context_policy.model_dump(),
            "requires_jd": router_output.requires_jd,
            "requires_evidence": router_output.requires_evidence,
            "risk_flags": router_output.risk_flags,
            "trace_metadata": router_output.trace_metadata,
        },
        duration_ms=elapsed_ms(started),
    )
    return {"qa": qa, "router_output": router_output, "last_decision_meta": meta}


def condition_normalizer_node(state: _GraphState) -> dict[str, Any]:
    """把 router raw conditions 归一化，写回 RouterOutput 并记录条件摘要。"""
    qa = state["qa"]
    started = time.perf_counter()
    router_output = normalize_router_output(state["router_output"], qa.question)
    qa.trace.router_output = router_output
    log_decision(
        qa,
        node="condition_normalizer",
        engine="rule",
        output={
            "conditions": [item.model_dump() for item in router_output.conditions],
            "normalized_conditions": [item.model_dump() for item in router_output.normalized_conditions],
            "context_policy": router_output.context_policy.model_dump(),
        },
        duration_ms=elapsed_ms(started),
    )
    return {"qa": qa, "router_output": router_output}


def execution_policy_node(state: _GraphState) -> dict[str, Any]:
    """解析执行策略，写回 ExecutionDecision；route 判断在 routes.py。"""
    qa = state["qa"]
    started = time.perf_counter()
    decision = resolve_execution_policy(qa.question, state["router_output"], state["config"])
    qa.trace.execution_decision = decision
    log_decision(qa, node="execution_policy", engine="rule", output=decision.model_dump(), duration_ms=elapsed_ms(started))
    return {"qa": qa, "execution_decision": decision}
