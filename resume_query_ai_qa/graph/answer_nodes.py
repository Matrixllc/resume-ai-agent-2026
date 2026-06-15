"""Graph adapters for answer generation, validation, rewrite, and fallback.

这个文件负责什么：
  aggregator、answer_validator、answer_rewrite、rule_answer_fallback 的 graph state
  读写、rewrite 计数和 trace 记录。

应该从哪个函数读起：
  aggregator_node() -> answer_validator_node() -> answer_rewrite_node()
  -> rule_answer_fallback_node()。

不会负责什么：
  不生成工具事实、不直接放行不合格答案；answer rewrite/fallback 后仍回
  answer_validator。
"""

from __future__ import annotations

import time
from typing import Any

from resume_query_ai_qa.core.answer_generation import aggregate_answer_with_meta
from resume_query_ai_qa.nodes.answer_rewrite import rewrite_answer
from resume_query_ai_qa.nodes.answer_validator import validate_answer
from resume_query_ai_qa.nodes.rule_answer_fallback import build_rule_fallback

from .state import _GraphState
from .trace_logging import (
    aggregator_domain_log,
    aggregator_io_debug,
    aggregator_io_log,
    aggregator_layout_log,
    answer_summary,
    log_decision,
)
from .utils import elapsed_ms, require_plan


def aggregator_node(state: _GraphState) -> dict[str, Any]:
    """基于已验证工具事实生成 AggregatedAnswer，并记录 answer/debug 摘要。"""
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
    """只读校验最终答案，写回 current_answer_* 字段供 answer route 使用。"""
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
    """根据答案校验问题生成 rewrite candidate，或请求确定性规则兜底。"""
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
    """仅使用现有工具事实生成确定性兜底答案；生成后仍回 answer_validator。"""
    started = time.perf_counter()
    qa = state["qa"]
    plan = require_plan(qa)
    answer, meta = build_rule_fallback(qa.question, plan, qa.tool_results, state["config"])
    qa.answer = answer
    qa.trace.aggregator_answer = answer.answer
    log_decision(qa, node="rule_answer_fallback", engine=meta["engine"], fallback_reason=meta.get("fallback_reason", ""), output=answer_summary(answer), duration_ms=elapsed_ms(started))
    return {"qa": qa, "answer_rewrites": int(state.get("answer_rewrites", 0)) + 1, "answer_fallback_requested": False}
