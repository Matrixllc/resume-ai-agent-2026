from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from resume_query_ai_qa.benchmarks.benchmark_support import (
    HYBRID_ENV,
    cases_for,
    expected_artifacts,
    expected_tools,
    print_result,
    route_case,
    state_summary,
)
from resume_query_ai_qa.core.config import load_config
from resume_query_ai_qa.core.llm import build_chat_model, is_llm_enabled, llm_identity
from resume_query_ai_qa.core.rules.behavior_contract import allowed_aggregator_modes
from resume_query_ai_qa.graph.runner import run


MODES = {
    "hybrid": HYBRID_ENV,
    "llm_only": {
        "RESUME_QA_WORKFLOW_TEMPLATE_COMPILER_ENABLED": "false",
    },
}


def main() -> int:
    """运行本基准的全部合同检查，汇总失败项并通过退出码反馈结果。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=sorted(MODES), default="hybrid")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--retries", type=int, default=1)
    args = parser.parse_args()
    os.environ.update(MODES[args.mode])
    cfg = load_config()
    if not is_llm_enabled(cfg):
        return print_result("llm acceptance benchmark", [f"LLM disabled: {llm_identity(cfg)}"])
    try:
        build_chat_model(cfg).invoke("Reply with OK.")
    except Exception as error:
        if "APIConnectionError" in type(error).__name__ or "Connection" in type(error).__name__:
            return print_result("llm acceptance benchmark", [f"environment network preflight failed: {type(error).__name__}"])
        return print_result("llm acceptance benchmark", [f"LLM preflight failed: {type(error).__name__}: {error}"])

    allowed_modes = set(allowed_aggregator_modes(cfg))
    failures: list[str] = []
    rejected = 0
    for round_index in range(max(args.repeat, 1)):
        print(f"ROUND: {round_index + 1}/{max(args.repeat, 1)}", flush=True)
        for case in cases_for("llm"):
            print(f"START: {case['id']} | family={case['family']}", flush=True)
            last: list[str] = []
            for _attempt in range(max(args.retries, 1)):
                state = run(str(case["question"]), session_context=dict(case.get("session", {}) or {}), use_llm=True, config=cfg)
                summary = state_summary(state)
                router = state.trace.router_output or route_case(case, cfg)
                expected = dict(case.get("expected", {}) or {})
                safety = dict(case.get("safety", {}) or {})
                last = []
                if summary["status"] != expected.get("status"):
                    last.append(f"status expected={expected.get('status')} actual={summary['status']}")
                if summary["intent"] != expected.get("intent"):
                    last.append(f"intent expected={expected.get('intent')} actual={summary['intent']}")
                if any(summary["engines"].get(node) == "rule_fallback" for node in ("router", "planner")):
                    last.append("router/planner silently fell back")
                if safety.get("forbid_tools") and summary["tool_results"]:
                    last.append(f"expected no executed tools, got {summary['tool_results']}")
                forbidden = set(safety.get("forbidden_tools", []) or []) & set(summary["tools"])
                if forbidden:
                    last.append(f"forbidden tools used {sorted(forbidden)}")
                missing_tools = set(expected_tools(cfg, router)) - set(summary["tools"])
                if expected.get("status") == "ok" and missing_tools:
                    last.append(f"missing contract tools {sorted(missing_tools)}")
                missing_artifacts = set(expected_artifacts(cfg, router)) - set(summary["artifacts"])
                if expected.get("status") == "ok" and missing_artifacts:
                    last.append(f"missing contract artifacts {sorted(missing_artifacts)}")
                if expected.get("status") == "ok" and (summary["plan_errors"] or summary["execution_errors"]):
                    last.append(f"validator errors plan={summary['plan_errors']} execution={summary['execution_errors']}")
                if summary["aggregator_mode"] == "llm_fill_rejected":
                    rejected += 1
                elif "aggregator" in summary["nodes"] and summary["aggregator_mode"] not in allowed_modes:
                    last.append(f"unsupported aggregator mode {summary['aggregator_mode']}")
                if not last:
                    break
            failures.extend(f"round{round_index + 1}:{case['id']}: {item}" for item in last)
    print(f"llm_fill_rejected={rejected}")
    return print_result("llm acceptance benchmark", failures)


if __name__ == "__main__":
    raise SystemExit(main())
