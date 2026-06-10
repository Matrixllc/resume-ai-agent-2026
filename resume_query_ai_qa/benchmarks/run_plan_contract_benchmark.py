from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from resume_query_ai_qa.benchmarks.benchmark_support import apply_hybrid_env, cases_for, compile_case, expected_tools, plan_calls, print_result
from resume_query_ai_qa.core.config import load_config
from resume_query_ai_qa.core.rules.behavior_contract import router_intents, tool_contract
from resume_query_ai_qa.core.rules.execution_policy_rules import scenario_for_intent


def main() -> int:
    """运行本基准的全部合同检查，汇总失败项并通过退出码反馈结果。"""
    apply_hybrid_env()
    cfg = load_config()
    failures: list[str] = []
    for case in cases_for("plan"):
        router, plan, _meta, validation = compile_case(case, cfg)
        tools = [call.name for call in plan_calls(plan)]
        allowed = set()
        forbidden = set()
        for intent in router_intents(router):
            contract = tool_contract(cfg, intent, scenario_for_intent(router, intent))
            allowed.update(contract["allowed"])
            forbidden.update(contract["forbidden"])
        if router.intent != "out_of_scope" and not validation.ok and dict(case.get("expected", {}) or {}).get("status") != "needs_clarification":
            failures.append(f"{case['id']}: validator errors={validation.errors}")
        illegal = set(tools) - allowed if allowed else set(tools)
        if illegal:
            failures.append(f"{case['id']}: tools outside policy {sorted(illegal)}")
        if set(tools) & forbidden:
            failures.append(f"{case['id']}: forbidden tools {sorted(set(tools) & forbidden)}")
        required = set(expected_tools(cfg, router))
        if router.intent != "out_of_scope" and not required.intersection(tools):
            failures.append(f"{case['id']}: no preferred contract tool present; tools={tools}")
        for binding in plan.artifact_bindings:
            if binding.accepted_producer and binding.accepted_producer not in tools:
                failures.append(f"{case['id']}: artifact producer missing {binding.accepted_producer}")
        failures.extend(_safety_failures(case, plan))
    return print_result("plan contract benchmark", failures)


def _safety_failures(case: dict, plan) -> list[str]:
    """执行参数级安全合同检查，防止岗位目标被误编译成候选硬筛。"""
    safety = dict(case.get("safety", {}) or {})
    failures: list[str] = []
    required_tools = {str(item) for item in list(safety.get("required_tools", []) or [])}
    if required_tools:
        tools = {call.name for call in plan_calls(plan)}
        missing = sorted(required_tools - tools)
        if missing:
            failures.append(f"{case['id']}: required tools missing {missing}")
    forbidden_filter_args = dict(safety.get("forbidden_filter_args", {}) or {})
    required_filter_args = dict(safety.get("required_filter_args", {}) or {})
    if not forbidden_filter_args and not required_filter_args:
        return failures
    seen_required = {str(key): set() for key in required_filter_args}
    for call in plan_calls(plan):
        if call.name != "filter_candidates":
            continue
        args = dict(call.arguments or {})
        for key, required_values in required_filter_args.items():
            values = args.get(str(key))
            if values is None:
                continue
            actual = {str(item) for item in (values if isinstance(values, list) else [values])}
            required = {str(item) for item in list(required_values or [])}
            seen_required[str(key)].update(actual & required)
        for key, forbidden_values in forbidden_filter_args.items():
            values = args.get(str(key))
            if values is None:
                continue
            actual = {str(item) for item in (values if isinstance(values, list) else [values])}
            forbidden = {str(item) for item in list(forbidden_values or [])}
            overlap = sorted(actual & forbidden)
            if overlap:
                failures.append(f"{case['id']}: filter_candidates {key} contains forbidden values {overlap}")
    for key, required_values in required_filter_args.items():
        required = {str(item) for item in list(required_values or [])}
        missing = sorted(required - seen_required[str(key)])
        if missing:
            failures.append(f"{case['id']}: filter_candidates {key} missing required values {missing}")
    return failures


if __name__ == "__main__":
    raise SystemExit(main())
