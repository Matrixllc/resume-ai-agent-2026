from __future__ import annotations

import time
from typing import Any

from resume_query_ai_qa.core.llm import is_llm_enabled
from resume_query_ai_qa.core.rules.session_context import scoped_session_context
from resume_query_ai_qa.core.schemas import AggregatedAnswer
from resume_query_ai_qa.core.answer_generation import aggregate_answer_with_meta
from resume_query_ai_qa.nodes.answer_rewrite import rewrite_answer
from resume_query_ai_qa.nodes.answer_validator import validate_answer
from resume_query_ai_qa.nodes.clarification import build_clarification
from resume_query_ai_qa.nodes.condition_normalizer import normalize_router_output
from resume_query_ai_qa.nodes.execution_policy import resolve_execution_policy
from resume_query_ai_qa.nodes.execution_repair import repair_execution_plan
from resume_query_ai_qa.nodes.execution_validator import validate_execution
from resume_query_ai_qa.nodes.executor import execute_plan_with_context
from resume_query_ai_qa.nodes.plan_compiler import compile_semantic_plan_with_meta
from resume_query_ai_qa.nodes.plan_repair import repair_plan
from resume_query_ai_qa.nodes.plan_validator import validate_plan
from resume_query_ai_qa.nodes.planner import resolve_semantic_plan, semantic_plan_from_router
from resume_query_ai_qa.nodes.router import route_question, route_question_llm
from resume_query_ai_qa.nodes.rule_answer_fallback import build_rule_fallback
from resume_query_ai_qa.state import build_updated_session_context

from .state import _GraphState
from .trace_logging import (
    aggregator_domain_log,
    aggregator_io_debug,
    aggregator_io_log,
    aggregator_layout_log,
    answer_summary,
    decision_meta,
    log_decision,
    plan_summary,
    record_plan,
    record_tool_results,
    ref_bindings_from_plan,
)
from .utils import elapsed_ms, iter_plan_calls, require_plan


def router_node(state: _GraphState) -> dict[str, Any]:
    """获取路由节点并返回。"""
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
        },
        duration_ms=elapsed_ms(started),
    )
    return {"qa": qa, "router_output": router_output, "last_decision_meta": meta}


def condition_normalizer_node(state: _GraphState) -> dict[str, Any]:
    """把路由条件归一化为工具可消费的结构，记录结果并返回图状态增量。"""
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
    """依据场景配置选择编译器和工作流，不执行工具，只记录策略决策。"""
    qa = state["qa"]
    started = time.perf_counter()
    decision = resolve_execution_policy(qa.question, state["router_output"], state["config"])
    qa.trace.execution_decision = decision
    log_decision(qa, node="execution_policy", engine="rule", output=decision.model_dump(), duration_ms=elapsed_ms(started))
    return {"qa": qa, "execution_decision": decision}


def planner_node(state: _GraphState) -> dict[str, Any]:
    """生成语义计划并记录规划来源；规则规划失败时可按配置使用大模型回退。"""
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
    """把语义计划编译为可执行 QueryPlan，并记录工具和引用绑定关系。"""
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
    """校验 QueryPlan 的工具权限、参数和引用合同，只报告问题，不直接修复。"""
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
    """根据结构化校验问题修复计划，并记录修复动作、原因和重试次数。"""
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


def executor_node(state: _GraphState) -> dict[str, Any]:
    """按计划顺序执行确定性工具，保存工具结果并记录调用 trace。"""
    started = time.perf_counter()
    qa = state["qa"]
    plan = require_plan(qa)
    tool_results = execute_plan_with_context(plan, current_session_context(state), state["config"])
    record_tool_results(qa, plan, tool_results)
    log_decision(
        qa,
        node="executor",
        engine="tools",
        output={"tool_calls": [call.model_dump() for call in iter_plan_calls(plan)], "tool_results_summary": qa.trace.tool_results_summary},
        duration_ms=elapsed_ms(started),
    )
    return {"qa": qa}


def execution_validator_node(state: _GraphState) -> dict[str, Any]:
    """校验工具结果是否满足计划和证据合同，只报告问题，不修改结果。"""
    started = time.perf_counter()
    qa = state["qa"]
    plan = require_plan(qa)
    validation = validate_execution(
        plan=plan,
        tool_results=qa.tool_results,
        config=state["config"],
        router_output=state.get("router_output"),
        session_context=current_session_context(state),
    )
    qa.execution_errors = validation.errors
    qa.trace.execution_validation_errors = []
    if validation.errors:
        qa.trace.execution_validation_errors.extend(validation.errors)
    log_decision(qa, node="execution_validator", engine="validator", output={"ok": validation.ok, "errors": validation.errors, "warnings": validation.warnings, "error_details": [item.model_dump() for item in validation.error_details]}, duration_ms=elapsed_ms(started))
    return {"qa": qa, "execution_validation_ok": validation.ok, "current_execution_errors": validation.errors, "current_execution_issues": validation.error_details}


def execution_repair_node(state: _GraphState) -> dict[str, Any]:
    """根据执行校验问题调整计划，为下一轮工具执行准备可重试方案。"""
    started = time.perf_counter()
    qa = state["qa"]
    repairs = int(state.get("execution_repairs", 0)) + 1
    qa.retry_count.planner += 1
    current_errors = state.get("current_execution_errors", [])
    plan, decision = repair_execution_plan(
        qa.question,
        require_plan(qa),
        state["router_output"],
        current_errors,
        qa.tool_results,
        session_context=current_session_context(state),
        config=state["config"],
        validation_issues=state.get("current_execution_issues", []),
    )
    record_plan(qa, plan)
    log_decision(
        qa,
        node="execution_repair",
        engine="rule",
        output={"repairs": repairs, "repair_action": decision["action"], "error_category": decision["category"], "repair_reason": decision["reason"], "previous_errors": current_errors, **plan_summary(plan)},
        duration_ms=elapsed_ms(started),
    )
    return {"qa": qa, "execution_repairs": repairs}


def current_session_context(state: _GraphState) -> dict[str, Any]:
    """返回本轮允许下游节点使用的会话上下文。"""
    return scoped_session_context(state.get("router_output"), state["qa"].session_context)


def aggregator_node(state: _GraphState) -> dict[str, Any]:
    """依据工具事实、证据引用和答案布局生成聚合答案，并记录生成元数据。"""
    started = time.perf_counter()
    qa = state["qa"]
    plan = require_plan(qa)
    answer, meta = aggregate_answer_with_meta(
        qa.question,
        plan,
        qa.tool_results,
        state["config"],
        use_llm=state["use_llm"],
        node="aggregator",
        execution_decision=state.get("execution_decision"),
        router_output=state.get("router_output"),
    )
    qa.answer = answer
    qa.trace.aggregator_answer = answer.answer
    aggregator_debug = {
        **aggregator_io_debug(meta),
        "claims": [claim.model_dump() for claim in answer.claims],
        "used_evidence_refs": [ref.model_dump() for ref in answer.used_evidence_refs],
    }
    log_decision(
        qa,
        node="aggregator",
        engine=meta["engine"],
        fallback_reason=meta["fallback_reason"],
        llm=meta.get("llm"),
        output={**answer_summary(answer), **aggregator_layout_log(meta), **aggregator_domain_log(meta), **aggregator_io_log(meta)},
        debug=aggregator_debug,
        duration_ms=elapsed_ms(started),
    )
    return {"qa": qa, "last_decision_meta": meta}


def answer_validator_node(state: _GraphState) -> dict[str, Any]:
    """校验答案的事实、证据和布局合同，只报告问题，不重写答案。"""
    started = time.perf_counter()
    qa = state["qa"]
    plan = require_plan(qa)
    if qa.answer is None:
        errors = ["missing answer"]
        warnings = []
        issues = []
        ok = False
    else:
        validation = validate_answer(answer=qa.answer, tool_results=qa.tool_results, plan=plan, config=state["config"])
        ok = validation.ok
        errors = validation.errors
        warnings = validation.warnings
        issues = validation.error_details
    qa.answer_errors = errors
    qa.trace.answer_validation_errors = []
    if errors:
        qa.trace.answer_validation_errors.extend(errors)
    log_decision(qa, node="answer_validator", engine="validator", output={"ok": ok, "errors": errors, "warnings": warnings, "error_details": [item.model_dump() for item in issues]}, duration_ms=elapsed_ms(started))
    return {"qa": qa, "answer_validation_ok": ok, "current_answer_errors": errors, "current_answer_issues": issues}


def answer_rewrite_node(state: _GraphState) -> dict[str, Any]:
    """根据答案校验问题重写答案；无法可靠修复时请求确定性规则兜底。"""
    started = time.perf_counter()
    qa = state["qa"]
    plan = require_plan(qa)
    rewrites = int(state.get("answer_rewrites", 0)) + 1
    qa.retry_count.aggregator_rewrite += 1
    answer, meta = rewrite_answer(
        question=qa.question,
        plan=plan,
        tool_results=qa.tool_results,
        previous_answer=qa.answer,
        answer_errors=state.get("current_answer_errors", []),
        answer_issues=state.get("current_answer_issues", []),
        config=state["config"],
        use_llm=state["use_llm"],
        execution_decision=state.get("execution_decision"),
        router_output=state.get("router_output"),
    )
    fallback_requested = answer is None or meta.get("engine") == "fallback_request"
    if answer is not None:
        qa.answer = answer
        qa.trace.aggregator_answer = answer.answer
    answer_log = answer_summary(answer) if answer is not None else {"rewrite_candidate": None, "fallback_requested": True}
    rewrite_debug = aggregator_io_debug(meta)
    if answer is not None:
        rewrite_debug = {
            **rewrite_debug,
            "claims": [claim.model_dump() for claim in answer.claims],
            "used_evidence_refs": [ref.model_dump() for ref in answer.used_evidence_refs],
        }
    log_decision(
        qa,
        node="answer_rewrite",
        engine=meta["engine"],
        fallback_reason=meta["fallback_reason"],
        llm=meta.get("llm"),
        output={"rewrites": rewrites, "answer_repair_policy": meta.get("answer_repair_policy", {}), "fallback_requested": fallback_requested, **answer_log, **aggregator_layout_log(meta), **aggregator_domain_log(meta), **aggregator_io_log(meta)},
        debug=rewrite_debug,
        duration_ms=elapsed_ms(started),
    )
    return {"qa": qa, "answer_rewrites": rewrites, "answer_fallback_requested": fallback_requested, "last_decision_meta": meta}


def rule_answer_fallback_node(state: _GraphState) -> dict[str, Any]:
    """仅使用工具事实和规则模板生成兜底答案，避免无依据的自由生成。"""
    started = time.perf_counter()
    qa = state["qa"]
    plan = require_plan(qa)
    answer, meta = build_rule_fallback(qa.question, plan, qa.tool_results, state["config"])
    qa.answer = answer
    qa.trace.aggregator_answer = answer.answer
    log_decision(qa, node="rule_answer_fallback", engine=meta["engine"], fallback_reason=meta.get("fallback_reason", ""), output=answer_summary(answer), duration_ms=elapsed_ms(started))
    return {"qa": qa, "answer_rewrites": int(state.get("answer_rewrites", 0)) + 1, "answer_fallback_requested": False}


def final_node(state: _GraphState) -> dict[str, Any]:
    """收口成功运行，构建下一轮会话上下文并记录最终状态。"""
    qa = state["qa"]
    qa.updated_session_context = build_updated_session_context(qa)
    qa.trace.updated_session_context = qa.updated_session_context
    log_decision(qa, node="final", engine="graph", output={"status": "ok", "updated_session_context_keys": sorted(qa.updated_session_context)})
    return {"qa": qa, "final_status": "ok"}


def clarification_node(state: _GraphState) -> dict[str, Any]:
    """根据当前结构化问题生成澄清问题和选项，并将运行标记为待澄清。"""
    qa = state["qa"]
    issues = state.get("current_plan_issues", []) or state.get("current_execution_issues", []) or state.get("current_answer_issues", [])
    question, options = build_clarification(qa, issues=issues, router_output=state.get("router_output"))
    qa.clarification_required = True
    qa.clarification_question = question
    qa.clarification_options = options
    qa.answer = AggregatedAnswer(answer=question, warnings=["needs_clarification"])
    qa.trace.clarification_required = True
    qa.trace.clarification_question = question
    qa.trace.clarification_options = options
    log_decision(qa, node="clarification", engine="graph", output={"status": "needs_clarification", "question": question, "options": options})
    return {"qa": qa, "final_status": "needs_clarification"}


def fail_node(state: _GraphState) -> dict[str, Any]:
    """收口不可恢复的失败，保留各阶段错误供 trace 和调用方诊断。"""
    qa = state["qa"]
    log_decision(qa, node="fail", engine="graph", output={"status": "failed", "plan_errors": qa.plan_errors, "execution_errors": qa.execution_errors, "answer_errors": qa.answer_errors})
    return {"qa": qa, "final_status": "failed"}
