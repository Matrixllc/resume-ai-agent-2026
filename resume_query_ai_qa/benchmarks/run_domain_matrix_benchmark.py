from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from resume_query_ai_qa.benchmarks.benchmark_support import load_matrix, print_result, route_case
from resume_query_ai_qa.core.config import load_config
from resume_query_ai_qa.core.rules.execution_policy_rules import scenario_for_intent


def main() -> int:
    """运行本基准的全部合同检查，汇总失败项并通过退出码反馈结果。"""
    cfg = load_config()
    matrix = dict(load_matrix().get("domain_matrix", {}) or {})
    failures: list[str] = []
    for template in matrix.get("templates", []) or []:
        for domain in matrix.get("domains", []) or []:
            case = {"question": str(template["question"]).format(domain=domain)}
            router = route_case(case, cfg)
            expected_intent = str(template["expected_intent"])
            if router.intent != expected_intent:
                failures.append(f"{template['id']}:{domain}: intent expected={expected_intent} actual={router.intent}")
            actual_scenario = scenario_for_intent(router, expected_intent)
            if actual_scenario != template["expected_scenario"]:
                failures.append(f"{template['id']}:{domain}: scenario expected={template['expected_scenario']} actual={actual_scenario}")
    return print_result("domain matrix benchmark", failures)


if __name__ == "__main__":
    raise SystemExit(main())
