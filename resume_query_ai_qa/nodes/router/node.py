"""Router pipeline entrypoint.

Read this file first. It only wires the five router stages and deliberately
keeps business rules in the sibling modules:

preprocess_router_question -> build_router_draft -> apply_router_guards ->
complete_router_conditions -> finalize_router_output.

This module does not inspect YAML rules directly, classify intent details, or
build tool plans. It turns a user question into the final RouterOutput by
delegating each stage to the focused module that owns it.

中文阅读提示：
这个文件是 router 节点的总入口，只负责把 5 个阶段串起来。
业务判断放在 rules.py / guard.py / finalizer.py 等文件里；这里不要读 YAML
细节，也不要生成工具计划。你读代码时先看 route_question_llm()，再看
run_router_pipeline()，主链路就清楚了。
"""

from __future__ import annotations

from typing import Any

from resume_query_ai_qa.core.config import ResumeQAConfig, load_config
from resume_query_ai_qa.core.llm import is_llm_enabled
from resume_query_ai_qa.core.schemas import RouterOutput

from . import rules
from .conditions import complete_router_conditions, preprocess_router_question
from .finalizer import finalize_router_output, safe_out_of_scope
from .guard import apply_router_guards
from .llm import build_llm_router_draft


def route_question(question: str, config: ResumeQAConfig | None = None) -> RouterOutput:
    """Rule-only router entrypoint.

    Reads YAML through ResumeQAConfig and always uses the deterministic rule
    draft. Later stages are identical to the LLM entrypoint.

    中文：
    纯规则入口，不走 LLM。它仍然会走完整 5 阶段 pipeline，只是在 draft 阶段
    固定使用 rules.py 生成 RouterOutput 草稿。
    """
    return run_router_pipeline(question, config or load_config(), use_llm=False)


def route_question_llm(question: str, config: ResumeQAConfig | None = None) -> RouterOutput:
    """LLM-first router entrypoint.

    The LLM should produce a complete RouterOutput draft. If LLM is disabled or
    the draft fails validation inside llm.py, the pipeline uses rule fallback.

    中文：
    LLM 优先入口。LLM 负责先给一个完整 RouterOutput 草稿；如果 LLM 没开、
    输出不合法，或者 scenario 合同不合法，就退回 rules.py 的规则草稿。
    """
    return run_router_pipeline(question, config or load_config(), use_llm=True)


def run_router_pipeline(question: str, config: ResumeQAConfig, *, use_llm: bool) -> RouterOutput:
    """Run the five router stages from raw question to final RouterOutput.

    Stage ownership:
    1. conditions.py cleans the question.
    2. llm.py or rules.py builds a RouterOutput draft.
    3. guard.py applies hard rule corrections.
    4. conditions.py completes missing QueryCondition items.
    5. finalizer.py recomputes authoritative derived fields.

    中文：
    这是 router 最核心的阅读线：清理问题 -> 生成草稿 -> 硬规则纠偏 ->
    补条件 -> 最终权威收口。后面所有复杂函数都服务这条线。
    """
    cleaned_question = preprocess_router_question(question, config)
    draft = build_router_draft(cleaned_question, config, use_llm=use_llm)
    guarded = apply_router_guards(draft, cleaned_question, config)
    completed = complete_router_conditions(guarded, cleaned_question, config)
    final = safe_finalize_router_output(completed, cleaned_question, config)
    return _with_router_audit(
        final,
        question=cleaned_question,
        draft=draft,
        guarded=guarded,
        completed=completed,
        draft_source=_draft_source(draft, config, use_llm=use_llm),
    )


def build_router_draft(question: str, config: ResumeQAConfig, *, use_llm: bool) -> RouterOutput:
    """Build the RouterOutput draft before guard and finalizer stages.

    Empty questions are immediately drafted as out_of_scope. LLM mode is only
    used when the runtime config enables it; otherwise the deterministic rule
    fallback produces the full draft.

    中文：
    这里只决定“草稿从哪里来”：空问题直接 out_of_scope；LLM 可用就先走 LLM；
    否则用规则 fallback。这里不做最终判断。
    """
    if not question:
        return rules.build_out_of_scope_draft(question, config)
    if use_llm and is_llm_enabled(config):
        return build_llm_router_draft(question, config)
    return rules.build_rule_router_draft(question, config)


def safe_finalize_router_output(output: RouterOutput, question: str, config: ResumeQAConfig) -> RouterOutput:
    """Finalize RouterOutput, safely degrading to out_of_scope on finalizer errors.

    中文：
    最后一道保险。如果 finalizer 自己报错，就返回安全的 out_of_scope，
    避免 router 节点把异常继续往后传。
    """
    try:
        return finalize_router_output(output, question, config)
    except Exception as error:
        return safe_out_of_scope(question, config, f"{type(error).__name__}: {str(error)[:120]}")


def _with_router_audit(
    final: RouterOutput,
    *,
    question: str,
    draft: RouterOutput,
    guarded: RouterOutput,
    completed: RouterOutput,
    draft_source: str,
) -> RouterOutput:
    """Attach router audit trace metadata without changing routing decisions."""
    snapshots = {
        "llm_or_rule_draft": _router_snapshot(draft),
        "guarded_output": _router_snapshot(guarded),
        "completed_output": _router_snapshot(completed),
        "final_router_output": _router_snapshot(final),
    }
    audit = _strip_empty(
        {
            "draft_source": draft_source,
            "draft_intent": draft.intent,
            "draft_scenario": _primary_scenario(draft),
            "final_intent": final.intent,
            "final_scenario": _primary_scenario(final),
            "field_changes": _router_field_changes(draft, guarded, completed, final),
            "hard_rules_applied": _hard_rules_applied(final, guarded),
            "hard_override_applied": bool(_hard_rules_applied(final, guarded)),
            "soft_hints": _router_soft_hints(question),
            "diagnostics": _router_diagnostics(final),
            "snapshots": snapshots,
        }
    )
    metadata = dict(final.trace_metadata or {})
    metadata["router_audit"] = audit
    return final.model_copy(update={"trace_metadata": metadata})


def _draft_source(draft: RouterOutput, config: ResumeQAConfig, *, use_llm: bool) -> str:
    if any(str(flag).startswith(("llm_router_fallback", "router_schema_validation_failed")) for flag in draft.risk_flags):
        return "rule"
    if use_llm and is_llm_enabled(config):
        return "llm"
    return "rule"


def _router_snapshot(output: RouterOutput) -> dict[str, Any]:
    return {
        "intent": output.intent,
        "is_compound": output.is_compound,
        "sub_intent_candidates": list(output.sub_intent_candidates),
        "scenario_decisions": {key: value.model_dump() for key, value in output.scenario_decisions.items()},
        "conditions": [item.model_dump() for item in output.conditions],
        "context_policy": output.context_policy.model_dump(),
        "requires_jd": output.requires_jd,
        "requires_evidence": output.requires_evidence,
        "allowed_tool_names": list(output.allowed_tool_names),
        "risk_flags": list(output.risk_flags),
    }


def _primary_scenario(output: RouterOutput) -> str:
    intent = output.sub_intent_candidates[0] if output.intent == "compound" and output.sub_intent_candidates else output.intent
    decision = output.scenario_decisions.get(str(intent))
    return decision.scenario if decision else ""


def _router_field_changes(
    draft: RouterOutput,
    guarded: RouterOutput,
    completed: RouterOutput,
    final: RouterOutput,
) -> list[dict[str, Any]]:
    fields = [
        "intent",
        "is_compound",
        "sub_intent_candidates",
        "scenario_decisions",
        "conditions",
        "context_policy",
        "requires_jd",
        "requires_evidence",
        "allowed_tool_names",
        "risk_flags",
    ]
    changes: list[dict[str, Any]] = []
    draft_snapshot = _router_snapshot(draft)
    guarded_snapshot = _router_snapshot(guarded)
    completed_snapshot = _router_snapshot(completed)
    final_snapshot = _router_snapshot(final)
    for field in fields:
        before = draft_snapshot.get(field)
        after = final_snapshot.get(field)
        source = "unchanged"
        reason = "draft value kept"
        if guarded_snapshot.get(field) != before:
            source = "hard_rule"
            reason = "router guard corrected the draft"
        elif completed_snapshot.get(field) != guarded_snapshot.get(field):
            source = "derived_recompute"
            reason = "condition completion recomputed router conditions"
        elif after != completed_snapshot.get(field):
            source = "contract_finalizer"
            reason = "finalizer enforced router contract or derived fields"
        if before != after or source != "unchanged":
            changes.append({"field": field, "before": before, "after": after, "source": source, "reason": reason})
    return changes


def _hard_rules_applied(final: RouterOutput, guarded: RouterOutput) -> list[dict[str, str]]:
    flags = [str(flag) for flag in [*guarded.risk_flags, *final.risk_flags] if str(flag).strip()]
    hard_flags = [flag for flag in rules.dedupe_rule_intents(flags) if _is_hard_router_flag(flag)]
    return [
        _strip_empty(
            {
                "rule": flag.split(":", 1)[0],
                "detail": flag.split(":", 1)[1] if ":" in flag else "",
                "action": "applied",
            }
        )
        for flag in hard_flags
    ]


def _is_hard_router_flag(flag: str) -> bool:
    prefixes = (
        "router_schema_validation_failed",
        "llm_router_fallback",
        "router_finalizer_failed",
        "condition_completion",
        "candidate_name",
        "context",
        "out_of_scope",
    )
    return any(flag == prefix or flag.startswith(f"{prefix}:") or flag.startswith(prefix) for prefix in prefixes)


def _router_soft_hints(question: str) -> list[dict[str, Any]]:
    hints: list[dict[str, Any]] = []
    job_fit_terms = ["适合", "推荐", "匹配", "胜任"]
    open_recall_terms = ["找找", "相关", "可能", "类似", "有没有"]
    hard_filter_terms = ["谁会", "谁有", "有哪些经验", "具备"]
    if matched := [term for term in job_fit_terms if term in question]:
        hints.append({"hint": "job_fit_query_detected", "tendency": "candidate_ranking", "matched_terms": matched})
    if matched := [term for term in open_recall_terms if term in question]:
        hints.append({"hint": "open_recall_terms_detected", "tendency": "candidate_filter/open_recall", "matched_terms": matched})
    if matched := [term for term in hard_filter_terms if term in question]:
        hints.append({"hint": "hard_filter_terms_detected", "tendency": "candidate_filter/hard_filter", "matched_terms": matched})
    return hints


def _router_diagnostics(output: RouterOutput) -> list[dict[str, Any]]:
    diagnostics: list[dict[str, Any]] = []
    preference_targets = [
        _strip_empty(
            {
                "type": condition.type,
                "value": condition.normalized_value or condition.raw_value,
                "matched_by": condition.matched_by,
            }
        )
        for condition in list(output.normalized_conditions or [])
        if str(condition.matched_by or "").startswith("preference_target:")
    ]
    scenario = _primary_scenario(output)
    if output.intent == "candidate_filter" and preference_targets:
        diagnostics.append({"diagnostic": "candidate_filter_with_preference_target", "preference_targets": preference_targets})
    if output.intent == "candidate_filter" and scenario == "hard_filter" and preference_targets:
        diagnostics.append({"diagnostic": "hard_filter_must_compile_preference_target_to_filter_args"})
    if output.intent == "candidate_filter" and scenario == "open_recall":
        diagnostics.append({"diagnostic": "open_recall_must_compile_non_empty_query"})
    if output.intent == "candidate_ranking" and preference_targets:
        diagnostics.append({"diagnostic": "ranking_uses_preference_target_as_target_role", "preference_targets": preference_targets})
    return diagnostics


def _strip_empty(value: dict[str, Any]) -> dict[str, Any]:
    return {
        key: item
        for key, item in value.items()
        if item is not None and item != "" and item != [] and item != {}
    }
