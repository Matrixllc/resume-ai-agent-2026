from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from resume_query_ai_qa.benchmarks.benchmark_support import cases_for, print_result, route_case, semantic_failures
from resume_query_ai_qa.core.config import load_config
from resume_query_ai_qa.core.inspection.plan_artifacts import artifact_bindings_from_plan
from resume_query_ai_qa.core.rules.behavior_contract import router_intents, tool_contract
from resume_query_ai_qa.core.rules.execution_policy_rules import resolve_scenario, scenario_for_intent
from resume_query_ai_qa.core.schemas import QueryPlan, RouterOutput, ToolCallSpec
from resume_query_ai_qa.nodes.router.finalizer import finalize_router_output
from resume_query_ai_qa.nodes.router.llm import validate_router_payload_schema


def main() -> int:
    """运行配置合同与代表性路由用例，确认运行行为由配置而非私有映射决定。"""
    cfg = load_config()
    failures: list[str] = []
    failures.extend(_configuration_truth_failures(cfg))
    failures.extend(_router_scenario_source_failures(cfg))
    for intent in dict(cfg.intents.get("intents", {}) or {}):
        for scenario in cfg.allowed_scenarios_for_intent(intent):
            contract = tool_contract(cfg, intent, scenario)
            overlap = set(contract["allowed"]) & set(contract["forbidden"])
            if overlap:
                failures.append(f"config:{intent}/{scenario}: allowed and forbidden overlap {sorted(overlap)}")
            missing = set(contract["preferred"]) - set(contract["allowed"])
            if missing:
                failures.append(f"config:{intent}/{scenario}: preferred not allowed {sorted(missing)}")
    for case in cases_for("policy"):
        router = route_case(case, cfg)
        failures.extend(f"{case['id']}: {item}" for item in semantic_failures(case, router))
        for intent in router_intents(router):
            scenario = scenario_for_intent(router, intent)
            if scenario not in cfg.allowed_scenarios_for_intent(intent):
                failures.append(f"{case['id']}: illegal intent/scenario {intent}/{scenario}")
    return print_result("policy contract benchmark", failures)


def _router_scenario_source_failures(config) -> list[str]:
    """验证 LLM 场景会被保留，非法场景会回到规则兜底。"""
    failures: list[str] = []
    question = "谁会 Python？"
    valid_payload = {
        "intent": "candidate_filter",
        "is_compound": False,
        "sub_intent_candidates": ["candidate_filter"],
        "sub_intent_evidence": [{"intent": "candidate_filter", "evidence": ["谁会", "Python"], "reason": "技能筛选"}],
        "scenario_decisions": {
            "candidate_filter": {
                "scenario": "hard_filter",
                "confidence": 0.91,
                "evidence": ["谁会", "Python"],
                "reason": "用户提出明确技能条件",
                "source": "llm",
            }
        },
        "conditions": [{"type": "skill", "raw_value": "Python", "evidence": "Python", "reason": "技能词"}],
        "normalized_conditions": [],
        "context_policy": {"uses_context": False, "context_ref_type": "none", "evidence": [], "reason": ""},
        "requires_jd": False,
        "requires_evidence": False,
        "allowed_tool_names": [],
        "risk_flags": [],
    }
    llm_output = finalize_router_output(validate_router_payload_schema(valid_payload, question, config), question, config)
    llm_decision = llm_output.scenario_decisions.get("candidate_filter")
    if not llm_decision or llm_decision.scenario != "hard_filter" or llm_decision.source != "llm":
        failures.append("router scenario source: valid LLM scenario was not preserved")

    invalid_payload = dict(valid_payload)
    invalid_payload["scenario_decisions"] = {
        "candidate_filter": {
            "scenario": "compare_rank",
            "confidence": 0.91,
            "evidence": ["谁会", "Python"],
            "reason": "非法场景",
            "source": "llm",
        }
    }
    fallback_output = validate_router_payload_schema(invalid_payload, question, config)
    fallback_decision = fallback_output.scenario_decisions.get("candidate_filter")
    if not fallback_decision or fallback_decision.source != "rule_fallback":
        failures.append("router scenario source: invalid LLM scenario did not fall back to rule scenario")
    if not any(flag.startswith("router_schema_validation_failed:") for flag in fallback_output.risk_flags):
        failures.append("router scenario source: invalid LLM scenario did not record schema fallback flag")
    return failures


def _configuration_truth_failures(config) -> list[str]:
    """修改内存中的配置副本，验证 scenario、planner 和 artifact binding 会同步变化。"""
    failures: list[str] = []

    scenario_cfg = config.model_copy(deep=True)
    scenario_cfg.scenarios["resolution_rules"]["candidate_count"]["default"] = "open_recall"
    output = RouterOutput(intent="candidate_count", sub_intent_candidates=["candidate_count"])
    if resolve_scenario("有多少候选人", output, "candidate_count", scenario_cfg) != "open_recall":
        failures.append("config truth: scenario resolution did not follow scenarios.yaml")

    planner_cfg = config.model_copy(deep=True)
    planner_cfg.scenarios["scenarios"]["hard_filter"]["planner"] = "llm"
    if planner_cfg.planner_for_scenarios({"candidate_count": "hard_filter"}) != "llm":
        failures.append("config truth: generic planner did not follow scenario planner metadata")

    artifact_cfg = config.model_copy(deep=True)
    artifact_cfg.tool_policy["tools"]["count_candidates"]["produces"] = ["candidate_profile"]
    bindings = artifact_bindings_from_plan(
        QueryPlan(intent="candidate_count", tool_calls=[ToolCallSpec(name="count_candidates", output_key="candidate_count")]),
        output,
        config=artifact_cfg,
    )
    if not bindings or bindings[0].artifact_type != "candidate_profile":
        failures.append("config truth: artifact binding did not follow tool_policy produces")
    return failures


if __name__ == "__main__":
    raise SystemExit(main())
