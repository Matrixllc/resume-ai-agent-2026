"""Graph adapters for planning and plan validation stages.

这个文件负责什么：
  planner、plan_compiler、plan_validator、plan_repair 的 graph state 读写、
  retry 计数和 trace 记录。

应该从哪个函数读起：
  planner_node() -> plan_compiler_node() -> plan_validator_node() -> plan_repair_node()。

不会负责什么：
  不实现语义规划、工具绑定或修复策略；这些规则在 nodes/planner、
  nodes/plan_compiler、nodes/plan_validator、nodes/plan_repair 内。
"""

from __future__ import annotations

import time
from typing import Any

from resume_query_ai_qa.nodes.plan_compiler import compile_semantic_plan_with_meta
from resume_query_ai_qa.nodes.plan_repair import repair_plan
from resume_query_ai_qa.nodes.plan_validator import validate_plan
from resume_query_ai_qa.nodes.planner import resolve_semantic_plan, semantic_plan_from_router

from .state import _GraphState
from .trace_logging import decision_meta, log_decision, plan_summary, record_plan, ref_bindings_from_plan
from .utils import current_session_context, elapsed_ms


def planner_node(state: _GraphState) -> dict[str, Any]:
    """生成 SemanticPlan，写入 trace；template 路径不会进入这个 adapter。"""
    qa = state["qa"]
    router_output = state["router_output"]
    started = time.perf_counter()
    semantic_plan, meta = resolve_semantic_plan(
        qa.question,
        router_output,
        state["execution_decision"],
        use_llm=state["use_llm"],
        config=state["config"],
    )
    qa.trace.semantic_plan = semantic_plan
    log_decision(
        qa,
        node="planner",
        engine=meta["engine"],
        fallback_reason=meta["fallback_reason"],
        llm=meta.get("llm"),
        output={"semantic_plan": semantic_plan.model_dump(), "semantic_compile_strategy": semantic_plan.compile_strategy},
        duration_ms=elapsed_ms(started),
    )
    return {"qa": qa, "semantic_plan": semantic_plan, "last_decision_meta": meta}


def plan_compiler_node(state: _GraphState) -> dict[str, Any]:
    """编译 QueryPlan 并记录工具调用、引用绑定和 compiler meta。"""
    qa = state["qa"]
    router_output = state["router_output"]
    semantic_plan = state.get("semantic_plan") or semantic_plan_from_router(
        router_output,
        state.get("execution_decision"),
        state["config"],
    )
    qa.trace.semantic_plan = semantic_plan
    started = time.perf_counter()
    context = current_session_context(state)
    plan, compiler_meta = compile_semantic_plan_with_meta(
        qa.question,
        router_output,
        semantic_plan,
        session_context=context,
        config=state["config"],
        decision=state.get("execution_decision"),
    )
    record_plan(qa, plan)
    compiler_debug = dict(compiler_meta.pop("debug", {}) or {})
    log_decision(
        qa,
        node="plan_compiler",
        engine="rule",
        output={
            "semantic_compile_strategy": semantic_plan.compile_strategy,
            "compile_notes": plan.notes,
            "ref_bindings": ref_bindings_from_plan(plan),
            **compiler_meta,
        },
        debug={"compiled_plan_summary": plan_summary(plan), **compiler_debug},
        duration_ms=elapsed_ms(started),
    )
    return {"qa": qa, "last_decision_meta": {"node": "plan_compiler", "engine": "rule", "fallback_reason": "", "compiler": compiler_meta}}


def plan_validator_node(state: _GraphState) -> dict[str, Any]:
    """只读校验 QueryPlan，写回 current_plan_errors/current_plan_issues 供 routes 使用。"""
    started = time.perf_counter()
    qa = state["qa"]
    if qa.plan is None:
        errors = ["missing plan"]
        issues = []
    else:
        context = current_session_context(state)
        validation = validate_plan(qa.plan, state["config"], router_output=state.get("router_output"), session_context=context)
        errors = validation.errors
        issues = validation.error_details
    qa.plan_errors = errors
    qa.trace.plan_validation_errors = []
    if errors:
        qa.trace.plan_validation_errors.extend(errors)
    log_decision(qa, node="plan_validator", engine="validator", output={"ok": not errors, "errors": errors, "error_details": [item.model_dump() for item in issues]}, duration_ms=elapsed_ms(started))
    return {"qa": qa, "plan_validation_ok": not errors, "current_plan_errors": errors, "current_plan_issues": issues}


def plan_repair_node(state: _GraphState) -> dict[str, Any]:
    """根据 plan validator 的结构化问题修复计划；修复后必须回 plan_validator。"""
    started = time.perf_counter()
    qa = state["qa"]
    repairs = int(state.get("plan_repairs", 0)) + 1
    qa.retry_count.planner += 1
    current_errors = state.get("current_plan_errors", [])
    plan, decision, engine, fallback_reason = repair_plan(
        qa.question,
        state["router_output"],
        qa.plan,
        current_errors,
        validation_issues=state.get("current_plan_issues", []),
        session_context=current_session_context(state),
        config=state["config"],
        use_llm=state["use_llm"],
    )
    meta = decision_meta("plan_repair", engine, fallback_reason, state["config"])
    record_plan(qa, plan)
    log_decision(
        qa,
        node="plan_repair",
        engine=meta["engine"],
        fallback_reason=meta["fallback_reason"],
        llm=meta.get("llm"),
        output={"repairs": repairs, "repair_action": decision["action"], "error_category": decision["category"], "repair_reason": decision["reason"], "previous_errors": current_errors, **plan_summary(plan)},
        duration_ms=elapsed_ms(started),
    )
    return {"qa": qa, "plan_repairs": repairs, "last_decision_meta": meta}
