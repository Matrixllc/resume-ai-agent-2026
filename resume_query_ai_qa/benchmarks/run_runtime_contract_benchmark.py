from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from resume_query_ai_qa.benchmarks.benchmark_support import apply_hybrid_env, cases_for, print_result, state_summary
from resume_query_ai_qa.core.config import load_config
from resume_query_ai_qa.core.rules.behavior_contract import allowed_aggregator_modes
from resume_query_ai_qa.graph.runner import run
from resume_query_api.routes.qa import _trace_summary


def main() -> int:
    """运行本基准的全部合同检查，汇总失败项并通过退出码反馈结果。"""
    apply_hybrid_env()
    cfg = load_config()
    allowed_modes = set(allowed_aggregator_modes(cfg))
    failures: list[str] = []
    for case in cases_for("runtime"):
        state = run(str(case["question"]), session_context=dict(case.get("session", {}) or {}), use_llm=False, config=cfg)
        summary = state_summary(state)
        expected = dict(case.get("expected", {}) or {})
        safety = dict(case.get("safety", {}) or {})
        if summary["status"] != expected.get("status"):
            failures.append(f"{case['id']}: status expected={expected.get('status')} actual={summary['status']}")
        if safety.get("forbid_tools") and summary["tool_results"]:
            failures.append(f"{case['id']}: expected no executed tools, got {summary['tool_results']}")
        used_forbidden = set(safety.get("forbidden_tools", []) or []) & set(summary["tools"])
        if used_forbidden:
            failures.append(f"{case['id']}: forbidden tools used {sorted(used_forbidden)}")
        if "aggregator" in summary["nodes"] and summary["aggregator_mode"] not in allowed_modes:
            failures.append(f"{case['id']}: unsupported aggregator mode {summary['aggregator_mode']}")
        if summary["tools"] and not set(summary["tool_results"]).issubset(set(summary["tools"])):
            failures.append(f"{case['id']}: tool result escaped executable plan")
        trace = _trace_summary(state)
        if not trace.get("router_scenarios"):
            failures.append(f"{case['id']}: debug trace missing router_scenarios")
        else:
            missing_source = [item for item in trace["router_scenarios"] if not item.get("source")]
            if missing_source:
                failures.append(f"{case['id']}: router_scenarios missing source")
    return print_result("runtime contract benchmark", failures)


if __name__ == "__main__":
    raise SystemExit(main())
