from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Iterable

import yaml

from resume_query_ai_qa.core.config import ResumeQAConfig, load_config
from resume_query_ai_qa.core.rules.behavior_contract import produced_artifacts, router_intents, tool_contract
from resume_query_ai_qa.core.rules.execution_policy_rules import scenario_for_intent
from resume_query_ai_qa.nodes.condition_normalizer import normalize_router_output
from resume_query_ai_qa.nodes.plan_compiler import compile_semantic_plan_with_meta
from resume_query_ai_qa.nodes.plan_validator import validate_plan
from resume_query_ai_qa.nodes.planner import semantic_plan_from_router
from resume_query_ai_qa.nodes.router import route_question


CASES_PATH = Path(__file__).with_name("benchmark_cases.yaml")
HYBRID_ENV = {
    "RESUME_QA_WORKFLOW_TEMPLATE_COMPILER_ENABLED": "true",
}


def load_matrix() -> dict[str, Any]:
    """执行loadmatrix合同检查；发现违规时追加失败项，不修改生产配置或数据。"""
    return dict(yaml.safe_load(CASES_PATH.read_text(encoding="utf-8")) or {})


def cases_for(tier: str) -> list[dict[str, Any]]:
    """执行casesfor合同检查；发现违规时追加失败项，不修改生产配置或数据。"""
    return [dict(case) for case in load_matrix().get("cases", []) if tier in list(case.get("tiers", []) or [])]


def route_case(case: dict[str, Any], config: ResumeQAConfig | None = None):
    """执行routecase合同检查；发现违规时追加失败项，不修改生产配置或数据。"""
    cfg = config or load_config()
    question = str(case["question"])
    return normalize_router_output(route_question(question, cfg), question)


def compile_case(case: dict[str, Any], config: ResumeQAConfig | None = None):
    """执行compilecase合同检查；发现违规时追加失败项，不修改生产配置或数据。"""
    cfg = config or load_config()
    router = route_case(case, cfg)
    semantic = semantic_plan_from_router(router)
    plan, meta = compile_semantic_plan_with_meta(
        str(case["question"]),
        router,
        semantic,
        session_context=dict(case.get("session", {}) or {}),
        config=cfg,
    )
    validation = validate_plan(plan, cfg, router_output=router, session_context=dict(case.get("session", {}) or {}))
    return router, plan, meta, validation


def plan_calls(plan) -> list[Any]:
    """执行计划调用合同检查；发现违规时追加失败项，不修改生产配置或数据。"""
    return [*plan.tool_calls, *(call for task in plan.sub_tasks for call in task.tool_calls)]


def expected_tools(config: ResumeQAConfig, router) -> list[str]:
    """执行expected工具合同检查；发现违规时追加失败项，不修改生产配置或数据。"""
    names: list[str] = []
    for intent in router_intents(router):
        scenario = scenario_for_intent(router, intent)
        names.extend(tool_contract(config, intent, scenario)["preferred"])
    return list(dict.fromkeys(names))


def expected_artifacts(config: ResumeQAConfig, router) -> list[str]:
    """执行expected产物合同检查；发现违规时追加失败项，不修改生产配置或数据。"""
    return produced_artifacts(config, expected_tools(config, router))


def semantic_failures(case: dict[str, Any], router) -> list[str]:
    """执行semanticfailures合同检查；发现违规时追加失败项，不修改生产配置或数据。"""
    expected = dict(case.get("expected", {}) or {})
    failures: list[str] = []
    if expected.get("intent") and router.intent != expected["intent"]:
        failures.append(f"intent expected={expected['intent']} actual={router.intent}")
    expected_sub = set(expected.get("sub_intents", []) or [])
    if expected_sub and expected_sub != set(router.sub_intent_candidates):
        failures.append(f"sub_intents expected={sorted(expected_sub)} actual={router.sub_intent_candidates}")
    if expected.get("context_ref_type") and router.context_policy.context_ref_type != expected["context_ref_type"]:
        failures.append(f"context expected={expected['context_ref_type']} actual={router.context_policy.context_ref_type}")
    if expected.get("no_conditions") and (router.conditions or router.normalized_conditions):
        failures.append(
            f"conditions expected=[] actual_raw={ [item.model_dump() for item in router.conditions] } "
            f"actual_normalized={ [item.model_dump() for item in router.normalized_conditions] }"
        )
    forbidden_candidate_names = {str(item) for item in list(expected.get("forbidden_candidate_names", []) or [])}
    if forbidden_candidate_names:
        actual_names = {
            str(getattr(item, "raw_value", "") or getattr(item, "normalized_value", "") or "")
            for item in [*router.conditions, *router.normalized_conditions]
            if getattr(item, "type", "") == "candidate_name"
        }
        overlap = sorted(forbidden_candidate_names & actual_names)
        if overlap:
            failures.append(f"candidate_name contains forbidden collection terms {overlap}")
    for intent, scenario in dict(expected.get("scenarios", {}) or {}).items():
        actual = scenario_for_intent(router, str(intent))
        if actual != scenario:
            failures.append(f"{intent} scenario expected={scenario} actual={actual}")
    return failures


def state_summary(state) -> dict[str, Any]:
    """执行状态摘要合同检查；发现违规时追加失败项，不修改生产配置或数据。"""
    plan = state.plan
    calls = plan_calls(plan) if plan is not None else []
    decisions = list(state.trace.decision_log or [])
    aggregator = next(
        (dict(item.get("output") or {}) for item in reversed(decisions) if item.get("node") in {"aggregator", "answer_rewrite"}),
        {},
    )
    return {
        "status": state.trace.final_status,
        "intent": state.intent,
        "tools": [call.name for call in calls],
        "tool_results": [item.tool_name for item in state.tool_results],
        "artifacts": [item.artifact_type for item in (plan.artifact_bindings if plan else [])],
        "nodes": [str(item.get("node") or "") for item in decisions],
        "engines": {str(item.get("node") or ""): str(item.get("engine") or "") for item in decisions},
        "aggregator_mode": str(aggregator.get("aggregator_io_mode") or ""),
        "answer": state.answer.answer if state.answer else "",
        "plan_errors": list(state.trace.plan_validation_errors or []),
        "execution_errors": list(state.trace.execution_validation_errors or []),
        "routes": list(state.trace.route_events or []),
    }


def print_result(name: str, failures: Iterable[str]) -> int:
    """执行print结果合同检查；发现违规时追加失败项，不修改生产配置或数据。"""
    items = list(failures)
    if items:
        print(f"FAILED: {name}")
        for item in items:
            print(f"- {item}")
        return 1
    print(f"OK: {name}")
    return 0


def apply_hybrid_env() -> None:
    """设置混合编译模式所需的测试环境变量。"""
    os.environ.update(HYBRID_ENV)
