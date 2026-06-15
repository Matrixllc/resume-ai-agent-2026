from __future__ import annotations

from typing import Any, Dict, List

from resume_query_ai_qa.core.schemas import ResumeQAState

from .qa_diagnosis import _diagnosis_summary
from .qa_utils import _compact_value, _result_count, _result_shape, _strip_empty


def _trace_summary(state: ResumeQAState) -> Dict[str, Any]:
    log_hint = f"data/logs/query_ai/*{state.trace.trace_id}*.json" if state.trace.trace_id else ""
    diagnosis = _diagnosis_summary(state)
    return {
        "trace_id": state.trace.trace_id,
        "intent": state.intent,
        "final_status": state.trace.final_status,
        "clarification_required": state.clarification_required,
        "diagnosis": diagnosis,
        "decision_steps": [
            _decision_step_summary(item)
            for item in state.trace.decision_log
        ],
        "node_details": _node_details(state),
        "route_events": [
            {
                "step": item.get("step"),
                "route_from": item.get("route_from", ""),
                "route_to": item.get("route_to", ""),
                "reason": item.get("reason", ""),
                "errors": item.get("errors", []),
                "retry_count": item.get("retry_count"),
            }
            for item in state.trace.route_events
        ],
        "tools": [
            {
                "name": result.tool_name,
                "status": "ok" if result.ok else "failed",
                "error": result.error,
                "warnings": result.warnings,
            }
            for result in state.tool_results
        ],
        "validation_errors": {
            "plan": state.trace.plan_validation_errors,
            "execution": state.trace.execution_validation_errors,
            "answer": state.trace.answer_validation_errors,
        },
        "retry_count": state.retry_count.model_dump(),
        "router_scenarios": _router_scenario_summary(state),
        "semantic_plan": state.trace.semantic_plan.model_dump() if state.trace.semantic_plan else None,
        "execution_decision": state.trace.execution_decision.model_dump() if state.trace.execution_decision else None,
        "compiled_plan": state.trace.planner_output.model_dump() if state.trace.planner_output else None,
        "compiler_decision": _compiler_decision_summary(state),
        "answer_claims": _answer_claim_summaries(state),
        "session_context_snapshot": _session_context_snapshot(state),
        "graph": _trace_graph(state),
        "log_file_hint": log_hint,
    }


def _router_scenario_summary(state: ResumeQAState) -> List[Dict[str, Any]]:
    """汇总 router 场景来源，供 debug trace 解释 LLM 与 rule fallback 的边界。"""
    router_output = state.trace.router_output
    if not router_output:
        return []
    rows: List[Dict[str, Any]] = []
    for intent, decision in router_output.scenario_decisions.items():
        rows.append(
            {
                "intent": intent,
                "scenario": decision.scenario,
                "source": decision.source,
                "confidence": decision.confidence,
                "reason": decision.reason,
                "evidence": decision.evidence,
            }
        )
    return rows


def _public_trace_summary(state: ResumeQAState) -> Dict[str, Any]:
    return {
        "trace_id": state.trace.trace_id,
        "intent": state.intent,
        "final_status": state.trace.final_status,
        "clarification_required": state.clarification_required,
    }


def _decision_step_summary(item: Dict[str, Any]) -> Dict[str, Any]:
    output = item.get("output") if isinstance(item.get("output"), dict) else {}
    ok = output.get("ok")
    errors = list(output.get("errors") or [])
    warnings = list(output.get("warnings") or [])
    status = output.get("status") or ("failed" if ok is False or errors else "ok")
    return {
        "step": item.get("step"),
        "node": item.get("node"),
        "engine": item.get("engine"),
        "llm": item.get("llm"),
        "status": status,
        "summary": _node_debug_summary(str(item.get("node") or ""), output),
        "fallback_reason": item.get("fallback_reason", ""),
        "duration_ms": item.get("duration_ms"),
        "repair_action": output.get("repair_action", ""),
        "repair_reason": output.get("repair_reason", ""),
        "error_category": output.get("error_category", ""),
        "errors": errors[:5],
        "warnings": warnings[:5],
    }


def _node_details(state: ResumeQAState) -> Dict[str, Dict[str, Any]]:
    """Build compact per-node debug details for the trace flow panel."""
    details: Dict[str, Dict[str, Any]] = {}
    for item in state.trace.decision_log:
        node = str(item.get("node") or "")
        if not node:
            continue
        output = item.get("output") if isinstance(item.get("output"), dict) else {}
        details[node] = _compact_value(_node_detail_for(state, node, item, output), max_items=8)
    return details


def _node_detail_for(
    state: ResumeQAState,
    node: str,
    item: Dict[str, Any],
    output: Dict[str, Any],
) -> Dict[str, Any]:
    routes = _routes_from_node(state, node)
    route_summary = [
        _strip_empty(
            {
                "to": route.get("route_to"),
                "reason": route.get("reason"),
                "errors": route.get("errors"),
                "retry_count": route.get("retry_count"),
            }
        )
        for route in routes
    ]
    router_output = state.trace.router_output
    semantic_plan = state.trace.semantic_plan.model_dump() if state.trace.semantic_plan else {}
    compiled_plan = state.trace.planner_output.model_dump() if state.trace.planner_output else {}

    base = {
        "title": node,
        "summary": _human_node_summary(state, node, output),
        "checks": _node_checks(state, node, output),
        "input": {},
        "decision": _strip_empty(
            {
                "engine": item.get("engine"),
                "fallback_reason": item.get("fallback_reason"),
                "duration_ms": item.get("duration_ms"),
            }
        ),
        "output": {},
        "advanced": {},
        "raw": _compact_value(output, max_items=6),
    }

    if node == "router":
        router_audit = _router_rule_audit(state, output)
        final_scenarios = router_audit.get("final_scenarios") or {}
        return {
            **base,
            "input": {
                "question": state.question,
                "session_context_keys": sorted((state.session_context or {}).keys()),
            },
            "decision": _strip_empty(
                {
                    **base["decision"],
                    "intent": output.get("intent"),
                    "scenario": (final_scenarios.get(output.get("intent")) if isinstance(final_scenarios, dict) else None)
                    or router_audit.get("final_scenario"),
                    "sub_intent_candidates": output.get("sub_intent_candidates"),
                    "scenario_decisions": output.get("scenario_decisions"),
                    "context_policy": output.get("context_policy"),
                    "requires_jd": output.get("requires_jd"),
                    "requires_evidence": output.get("requires_evidence"),
                    "hard_override_applied": router_audit.get("hard_override_applied"),
                }
            ),
            "output": _strip_empty(
                {
                    "intent": output.get("intent"),
                    "scenario": (final_scenarios.get(output.get("intent")) if isinstance(final_scenarios, dict) else None)
                    or router_audit.get("final_scenario"),
                    "conditions": output.get("conditions"),
                    "risk_flags": output.get("risk_flags"),
                }
            ),
            "advanced": _strip_empty({"router_audit": router_audit}),
        }

    if node == "condition_normalizer":
        normalized = output.get("normalized_conditions") or []
        return {
            **base,
            "input": {"conditions": output.get("conditions") or (router_output.conditions if router_output else [])},
            "decision": _strip_empty(
                {
                    **base["decision"],
                    "matches": [
                        _strip_empty(
                            {
                                "type": item.get("type"),
                                "value": item.get("normalized_value") or item.get("raw_value"),
                                "matched_by": item.get("matched_by"),
                                "confidence": item.get("confidence"),
                                "retrieval_terms": item.get("retrieval_terms"),
                            }
                        )
                        for item in normalized
                        if isinstance(item, dict)
                    ],
                    "context_policy": output.get("context_policy"),
                }
            ),
            "output": {"normalized_conditions": normalized},
        }

    if node == "execution_policy":
        decision = output.get("execution_decision") if isinstance(output.get("execution_decision"), dict) else output
        return {
            **base,
            "input": _strip_empty(
                {
                    "intent": router_output.intent if router_output else state.intent,
                    "scenario_decisions": router_output.scenario_decisions if router_output else {},
                }
            ),
            "decision": _strip_empty(
                {
                    **base["decision"],
                    "compiler": decision.get("compiler"),
                    "workflow_name": decision.get("workflow_name"),
                    "planner": decision.get("planner"),
                    "reason": decision.get("reason"),
                }
            ),
            "output": {"routes": route_summary},
        }

    if node == "planner":
        return {
            **base,
            "input": _strip_empty({"router_intent": state.intent, "context_policy": _router_context_policy(router_output)}),
            "decision": _strip_empty({**base["decision"], "semantic_plan": _semantic_plan_summary(semantic_plan)}),
            "output": {"steps": semantic_plan.get("steps") or []},
        }

    if node == "plan_compiler":
        return {
            **base,
            "input": _strip_empty(
                {
                    "semantic_plan": _semantic_plan_summary(semantic_plan),
                    "context_policy": _router_context_policy(router_output),
                }
            ),
            "decision": _strip_empty(
                {
                    **base["decision"],
                    "strategy": output.get("strategy") or output.get("semantic_compile_strategy") or output.get("compiler_strategy"),
                    "workflow_name": output.get("workflow_name"),
                }
            ),
            "output": {"tool_calls": _readable_tool_calls(_compiled_plan_tool_calls(compiled_plan))},
            "advanced": _strip_empty(
                {
                    "参数引用绑定": output.get("ref_bindings"),
                    "产物来源绑定": compiled_plan.get("artifact_bindings"),
                    "raw_tool_calls": _compiled_plan_tool_calls(compiled_plan),
                }
            ),
        }

    if node == "plan_validator":
        return {
            **base,
            "input": {"compiled_tool_calls": _readable_tool_calls(_compiled_plan_tool_calls(compiled_plan))},
            "decision": _strip_empty(
                {
                    **base["decision"],
                    "ok": output.get("ok"),
                    "errors": output.get("errors"),
                    "error_details": output.get("error_details"),
                }
            ),
            "output": {"routes": route_summary},
        }

    if node == "executor":
        calls = _compiled_plan_tool_calls(compiled_plan)
        return {
            **base,
            "input": {"tool_calls": _readable_tool_calls(calls)},
            "decision": {"depends_on": [{call.get("name"): call.get("depends_on") or []} for call in calls]},
            "output": {"tool_results": _tool_result_summaries(state)},
            "advanced": _strip_empty(
                {
                    "raw_tool_calls": calls,
                    "raw_tool_results": _compact_value([result.model_dump() for result in state.tool_results], max_items=8),
                }
            ),
        }

    if node == "execution_validator":
        return {
            **base,
            "input": {"tool_results": _tool_result_summaries(state)},
            "decision": _strip_empty(
                {
                    **base["decision"],
                    "requires_evidence": _plan_requires_evidence(state),
                    "empty_evidence_allowed": bool(output.get("ok") and any("evidence" in str(item).lower() for item in output.get("warnings", []) or [])),
                    "ok": output.get("ok"),
                    "errors": output.get("errors"),
                    "warnings": output.get("warnings"),
                    "error_details": output.get("error_details"),
                }
            ),
            "output": {"routes": route_summary},
        }

    if node in {"aggregator", "answer_rewrite", "rule_answer_fallback"}:
        return {
            **base,
            "input": _strip_empty(
                {
                    "answer_layout": output.get("answer_layout"),
                    "context_summary": output.get("context_summary"),
                }
            ),
            "decision": _strip_empty(
                {
                    **base["decision"],
                    "llm_mode": output.get("llm_mode"),
                    "aggregator_io_mode": output.get("aggregator_io_mode"),
                    "fallback_reason": item.get("fallback_reason") or output.get("fallback_reason"),
                    "empty_flags": (output.get("context_summary") or {}).get("empty_flags") if isinstance(output.get("context_summary"), dict) else None,
                    "warnings": output.get("warnings"),
                }
            ),
            "output": _strip_empty(
                {
                    "answer_preview": output.get("answer_preview"),
                    "claim_count": output.get("claim_count"),
                    "claims": _answer_claim_summaries(state),
                    "used_evidence_count": output.get("used_evidence_count"),
                }
            ),
            "advanced": {"完整结构化事实": _answer_claim_summaries(state)},
        }

    if node == "answer_validator":
        answer = state.answer.model_dump() if state.answer else {}
        return {
            **base,
            "input": _strip_empty(
                {
                    "claim_count": len(answer.get("claims") or []),
                    "claims": _answer_claim_summaries(state),
                    "used_evidence_count": len(answer.get("used_evidence_refs") or []),
                    "warnings": answer.get("warnings"),
                }
            ),
            "decision": _strip_empty(
                {
                    **base["decision"],
                    "ok": output.get("ok"),
                    "errors": output.get("errors"),
                    "error_details": output.get("error_details"),
                }
            ),
            "output": {"routes": route_summary},
            "advanced": {"完整结构化事实": _answer_claim_summaries(state)},
        }

    if node in {"final", "fail", "clarification"}:
        return {
            **base,
            "input": {"status_before_node": state.trace.final_status},
            "decision": _strip_empty({**base["decision"], "status": output.get("status")}),
            "output": _strip_empty(
                {
                    "plan_errors": output.get("plan_errors"),
                    "execution_errors": output.get("execution_errors"),
                    "answer_errors": output.get("answer_errors"),
                    "updated_session_context_keys": output.get("updated_session_context_keys"),
                }
            ),
        }

    return {
        **base,
        "input": {},
        "decision": _strip_empty({**base["decision"], "errors": output.get("errors"), "warnings": output.get("warnings")}),
        "output": _strip_empty({"routes": route_summary, "summary": _node_debug_summary(node, output)}),
    }


def _routes_from_node(state: ResumeQAState, node: str) -> List[Dict[str, Any]]:
    return [item for item in state.trace.route_events if item.get("route_from") == node]


def _router_context_policy(router_output: Any) -> Dict[str, Any]:
    if not router_output:
        return {}
    policy = router_output.context_policy
    return policy.model_dump() if hasattr(policy, "model_dump") else dict(policy or {})


def _semantic_plan_summary(plan: Dict[str, Any]) -> Dict[str, Any]:
    return _strip_empty(
        {
            "intent": plan.get("intent"),
            "is_compound": plan.get("is_compound"),
            "context_policy": plan.get("context_policy"),
            "steps": [
                _strip_empty(
                    {
                        "intent": step.get("intent"),
                        "scenario": step.get("scenario"),
                        "needs": step.get("needs"),
                        "tool_hints": step.get("tool_hints"),
                    }
                )
                for step in plan.get("steps") or []
                if isinstance(step, dict)
            ],
        }
    )


def _tool_result_summaries(state: ResumeQAState) -> List[Dict[str, Any]]:
    return [
        _strip_empty(
            {
                "name": result.tool_name,
                "ok": result.ok,
                "error": result.error,
                "warnings": result.warnings,
                "result_shape": _result_shape(result.data),
                "result_count": _result_count(result.data),
            }
        )
        for result in state.tool_results
    ]


def _readable_tool_calls(calls: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Build human-readable tool call summaries for the frontend."""
    return [
        _strip_empty(
            {
                "name": call.get("name"),
                "purpose": call.get("purpose") or _tool_purpose(str(call.get("name") or "")),
                "output_key": call.get("output_key"),
                "depends_on": call.get("depends_on") or [],
                "arguments": _readable_arguments(dict(call.get("arguments") or {})),
            }
        )
        for call in calls
    ]


def _readable_arguments(arguments: Dict[str, Any]) -> Dict[str, Any]:
    return {key: _readable_argument_value(value) for key, value in arguments.items()}


def _readable_argument_value(value: Any) -> Any:
    if isinstance(value, dict) and "$ref" in value:
        root = str(value.get("$ref") or "")
        path = ".".join(str(item) for item in list(value.get("path") or []))
        suffix = "[]" if value.get("map") else ""
        return f"{root}{'.' if path else ''}{path}{suffix}"
    if isinstance(value, dict):
        return {key: _readable_argument_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_readable_argument_value(item) for item in value]
    return value


def _tool_purpose(name: str) -> str:
    purposes = {
        "filter_candidates": "按领域、技能、专业等条件筛候选人",
        "count_candidates": "统计候选人数量",
        "resolve_candidate_reference": "把用户提到的人名或上下文指代解析成候选人 ID",
        "search_candidate_evidence": "在指定候选人的简历证据中检索项目/经历",
        "get_candidate_profiles_intro": "读取候选人画像摘要",
        "get_candidate_profile_intro": "读取单个候选人画像摘要",
        "load_default_jd_criteria": "加载默认岗位评分标准",
        "score_candidates_for_jd": "按岗位标准给候选人打分",
        "rank_candidates": "按评分结果排序候选人",
        "build_comparison_pack": "构建双人比较事实包",
    }
    return purposes.get(name, "执行计划中的工具调用")


def _answer_claim_summaries(state: ResumeQAState) -> List[Dict[str, Any]]:
    if not state.answer:
        return []
    return [
        _strip_empty(
            {
                "type": claim.claim_type,
                "subject": claim.subject,
                "text": claim.text,
                "value": claim.value,
                "supported_by": claim.supported_by,
                "evidence_ids": claim.evidence_ids,
            }
        )
        for claim in state.answer.claims
    ]


def _human_node_summary(state: ResumeQAState, node: str, output: Dict[str, Any]) -> str:
    if node == "plan_compiler":
        decision = state.trace.execution_decision
        plan = state.trace.planner_output.model_dump() if state.trace.planner_output else {}
        workflow = getattr(decision, "workflow_name", "") if decision else ""
        compiler = getattr(decision, "compiler", "") if decision else ""
        return f"选择 {compiler or '-'}，命中 {workflow or '无 workflow'}，生成 {len(_compiled_plan_tool_calls(plan))} 个工具调用。"
    if node == "executor":
        results = _tool_result_summaries(state)
        ok = len([item for item in results if item.get("ok")])
        failed = len(results) - ok
        return f"执行 {len(results)} 个工具：{ok} 个成功，{failed} 个失败。"
    if node == "plan_validator":
        return "执行前检查 QueryPlan 的工具权限、参数引用、依赖和产物来源。"
    if node == "execution_validator":
        return "执行后检查工具结果是否满足证据、数量、排序和空结果语义。"
    if node == "answer_validator":
        return "出口前检查答案文本、结构化事实、证据引用、布局和隐私。"
    if node in {"aggregator", "answer_rewrite", "rule_answer_fallback"}:
        return "基于工具事实组织答案，并生成用于校验的结构化事实。"
    return _node_debug_summary(node, output)


def _node_checks(state: ResumeQAState, node: str, output: Dict[str, Any]) -> List[Dict[str, Any]]:
    if node == "plan_validator":
        errors = list(output.get("errors") or [])
        return [
            _check("工具权限", not _has_error(errors, "tool"), "工具在当前 intent/scenario 允许范围内"),
            _check("参数绑定", not _has_error(errors, "arg") and not _has_error(errors, "binding"), "工具参数和 $ref 引用可解析"),
            _check("依赖关系", not _has_error(errors, "depend"), "depends_on 指向已生成的 output_key"),
            _check("上下文", not _has_error(errors, "context"), "需要的会话上下文存在"),
            _check("产物来源", not _has_error(errors, "artifact") and not _has_error(errors, "source"), "候选池、排序、证据等产物来源一致"),
        ]
    if node == "execution_validator":
        results = _tool_result_summaries(state)
        return [
            _check("工具执行", all(item.get("ok") for item in results), f"{len(results)} 个工具结果"),
            _check("失败工具", not any(not item.get("ok") for item in results), "没有工具失败"),
            _check("证据要求", not output.get("errors"), "需要证据时已返回或允许明确空证据"),
            _check("空结果语义", not output.get("errors"), "空结果没有被误判成相反结论"),
        ]
    if node == "answer_validator":
        errors = list(output.get("errors") or [])
        claims = _answer_claim_summaries(state)
        return [
            _check("结构化事实", not _has_error(errors, "claim"), f"{len(claims)} 条 claims"),
            _check("候选人/数量/排序", not any(_has_error(errors, key) for key in ["name", "count", "ranking"]), "答案中的对象来自工具结果"),
            _check("证据引用", not _has_error(errors, "evidence"), "used_evidence_refs 和 evidence_ids 合法"),
            _check("布局/隐私", not any(_has_error(errors, key) for key in ["layout", "privacy"]), "答案布局和隐私检查通过"),
        ]
    return []


def _check(label: str, ok: bool, detail: str = "") -> Dict[str, Any]:
    return {"label": label, "status": "ok" if ok else "failed", "detail": detail}


def _has_error(errors: List[Any], token: str) -> bool:
    token = token.lower()
    return any(token in str(error).lower() for error in errors)


def _plan_requires_evidence(state: ResumeQAState) -> bool:
    if state.trace.router_output and state.trace.router_output.requires_evidence:
        return True
    plan = state.plan
    if not plan:
        return False
    return bool(
        any(getattr(sub_task, "requires_evidence", False) for sub_task in plan.sub_tasks)
    )


def _node_debug_summary(node: str, output: Dict[str, Any]) -> str:
    if node == "router":
        return f"intent={output.get('intent') or '-'}"
    if node == "condition_normalizer":
        return f"normalized_conditions={len(output.get('normalized_conditions') or [])}"
    if node == "execution_policy":
        decision = output.get("execution_decision") or {}
        return f"compiler={decision.get('compiler') or output.get('compiler') or '-'}"
    if node == "planner":
        plan = output.get("semantic_plan") or {}
        return f"semantic={plan.get('intent') or '-'} steps={len(plan.get('steps') or [])}"
    if node == "plan_compiler":
        plan = output.get("compiled_plan") or {}
        return f"mode={output.get('compiler_mode') or '-'} tools={len(plan.get('tool_calls') or [])}"
    if node == "executor":
        return f"tools={len(output.get('tool_results_summary') or [])}"
    if node in {"plan_validator", "execution_validator", "answer_validator"}:
        return "ok" if output.get("ok") else f"errors={len(output.get('errors') or [])}"
    if node in {"plan_repair", "execution_repair"}:
        return f"repair={output.get('repair_action') or '-'} reason={output.get('repair_reason') or '-'}"
    if node in {"aggregator", "answer_rewrite", "rule_answer_fallback"}:
        return f"claims={output.get('claim_count', 0)} evidence={output.get('used_evidence_count', 0)}"
    if node == "final":
        return f"status={output.get('status') or '-'}"
    return ""


def _router_rule_audit(state: ResumeQAState, output: Dict[str, Any]) -> Dict[str, Any]:
    """Build a readable hard/soft/diagnostic router rule audit for debug trace."""
    router_output = state.trace.router_output
    trace_metadata = output.get("trace_metadata") if isinstance(output.get("trace_metadata"), dict) else {}
    if not trace_metadata and router_output is not None:
        trace_metadata = getattr(router_output, "trace_metadata", {}) or {}
    if isinstance(trace_metadata, dict) and isinstance(trace_metadata.get("router_audit"), dict):
        return trace_metadata["router_audit"]
    question = str(state.question or "")
    final_intent = str(output.get("intent") or getattr(router_output, "intent", "") or "")
    scenarios = output.get("scenario_decisions") or {}
    final_scenarios = {
        str(intent): (dict(decision).get("scenario") if isinstance(decision, dict) else getattr(decision, "scenario", ""))
        for intent, decision in (scenarios.items() if isinstance(scenarios, dict) else [])
    }
    risk_flags = [str(item) for item in list(output.get("risk_flags") or getattr(router_output, "risk_flags", []) or []) if str(item).strip()]
    hard_rules = [
        _strip_empty({"rule": flag.split(":", 1)[0], "detail": flag.split(":", 1)[1] if ":" in flag else "", "action": "applied"})
        for flag in risk_flags
        if _is_hard_router_flag(flag)
    ]
    return _strip_empty(
        {
            "draft_source": output.get("engine") or _router_engine_from_log(state),
            "final_intent": final_intent,
            "final_scenarios": final_scenarios,
            "hard_rules_applied": hard_rules,
            "hard_override_applied": bool(hard_rules),
            "soft_hints": _router_soft_hints(question),
            "diagnostics": _router_diagnostics(router_output, final_intent, final_scenarios),
            "llm_decision_kept": not bool(hard_rules),
        }
    )


def _router_engine_from_log(state: ResumeQAState) -> str:
    for item in state.trace.decision_log:
        if item.get("node") == "router":
            return str(item.get("engine") or "")
    return ""


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


def _router_soft_hints(question: str) -> List[Dict[str, Any]]:
    text = str(question or "")
    hints: List[Dict[str, Any]] = []
    job_fit_terms = ["适合", "推荐", "匹配", "胜任"]
    open_recall_terms = ["找找", "相关", "可能", "类似", "有没有"]
    hard_filter_terms = ["谁会", "谁有", "有哪些经验", "具备"]
    if any(term in text for term in job_fit_terms):
        hints.append({"hint": "job_fit_query_detected", "tendency": "candidate_ranking", "matched_terms": [term for term in job_fit_terms if term in text]})
    if any(term in text for term in open_recall_terms):
        hints.append({"hint": "open_recall_terms_detected", "tendency": "candidate_filter/open_recall", "matched_terms": [term for term in open_recall_terms if term in text]})
    if any(term in text for term in hard_filter_terms):
        hints.append({"hint": "hard_filter_terms_detected", "tendency": "candidate_filter/hard_filter", "matched_terms": [term for term in hard_filter_terms if term in text]})
    return hints


def _router_diagnostics(router_output: Any, final_intent: str, final_scenarios: Dict[str, Any]) -> List[Dict[str, Any]]:
    if router_output is None:
        return []
    diagnostics: List[Dict[str, Any]] = []
    preference_targets = [
        _strip_empty(
            {
                "type": getattr(condition, "type", ""),
                "value": getattr(condition, "normalized_value", "") or getattr(condition, "raw_value", ""),
                "matched_by": getattr(condition, "matched_by", ""),
            }
        )
        for condition in list(getattr(router_output, "normalized_conditions", []) or [])
        if str(getattr(condition, "matched_by", "") or "").startswith("preference_target:")
    ]
    scenario = str(final_scenarios.get(final_intent) or "")
    if final_intent == "candidate_filter" and preference_targets:
        diagnostics.append({"diagnostic": "candidate_filter_with_preference_target", "preference_targets": preference_targets})
    if final_intent == "candidate_filter" and scenario == "hard_filter" and preference_targets:
        diagnostics.append({"diagnostic": "hard_filter_must_compile_preference_target_to_filter_args"})
    if final_intent == "candidate_filter" and scenario == "open_recall":
        diagnostics.append({"diagnostic": "open_recall_must_compile_non_empty_query"})
    if final_intent == "candidate_ranking" and preference_targets:
        diagnostics.append({"diagnostic": "ranking_uses_preference_target_as_target_role", "preference_targets": preference_targets})
    return diagnostics


def _compiler_decision_summary(state: ResumeQAState) -> Dict[str, Any]:
    output = _decision_output(state, "plan_compiler")
    if not output:
        return {}
    debug = output.get("debug") if isinstance(output.get("debug"), dict) else {}
    compiler_output = {**debug, **{key: value for key, value in output.items() if key not in {"debug"}}}
    plan = compiler_output.get("compiled_plan") or {}
    tool_calls = _compiled_plan_tool_calls(plan)
    final_tools = [str(call.get("name") or "") for call in tool_calls if isinstance(call, dict)]
    decisions = _hint_tool_decisions(state, compiler_output, final_tools)
    return {
        "compiler_mode": compiler_output.get("compiler_mode", ""),
        "compiler_config_mode": compiler_output.get("compiler_config_mode") or compiler_output.get("compiler_mode", ""),
        "compiler_strategy": compiler_output.get("compiler_strategy") or compiler_output.get("compiler_mode", ""),
        "compiler_source": compiler_output.get("compiler_source") or "",
        "workflow_name": compiler_output.get("workflow_name") or "",
        "compiler_enabled_flags": compiler_output.get("compiler_enabled_flags") or compiler_output.get("compiler_flags") or {},
        "selection_rule": "source contract > workflow/template > allowed tools > confidence tie-break",
        "hint_tool_decisions": decisions,
        "final_tool_calls": [
            {
                "index": index,
                "name": call.get("name", ""),
                "output_key": call.get("output_key", ""),
                "depends_on": call.get("depends_on") or [],
            }
            for index, call in enumerate(tool_calls)
            if isinstance(call, dict)
        ],
    }


def _compiled_plan_tool_calls(plan: Any) -> List[Dict[str, Any]]:
    if not isinstance(plan, dict):
        return []
    output = [call for call in list(plan.get("tool_calls") or []) if isinstance(call, dict)]
    for sub_task in list(plan.get("sub_tasks") or []):
        if isinstance(sub_task, dict):
            output.extend(call for call in list(sub_task.get("tool_calls") or []) if isinstance(call, dict))
    return output


def _decision_output(state: ResumeQAState, node: str) -> Dict[str, Any]:
    for item in state.trace.decision_log:
        if item.get("node") == node and isinstance(item.get("output"), dict):
            return item["output"]
    return {}


def _hint_tool_decisions(state: ResumeQAState, compiler_output: Dict[str, Any], final_tools: List[str]) -> List[Dict[str, Any]]:
    hint_map: Dict[str, Dict[str, Any]] = {}
    if state.trace.semantic_plan:
        for step in state.trace.semantic_plan.steps:
            scored = step.tool_hint_scores or []
            if scored:
                for hint in scored:
                    _merge_hint(hint_map, hint.name, step.intent, hint.confidence, hint.source, hint.reason)
            else:
                for name in step.tool_hints:
                    _merge_hint(hint_map, name, step.intent, 0.5, "legacy_default", "legacy tool_hints default confidence")
    for item in compiler_output.get("llm_tool_hint_scores") or []:
        if isinstance(item, dict):
            source = "legacy_default" if str(item.get("reason", "")).startswith("legacy tool_hints") else str(item.get("source") or "llm_scored")
            _merge_hint(hint_map, str(item.get("name") or ""), "", float(item.get("confidence") or 0.0), source, str(item.get("reason") or ""))

    rejected_by_tool = {
        str(item["tool"]): item
        for item in compiler_output.get("rejected_tool_hints") or []
        if isinstance(item, dict) and item.get("tool")
    }
    artifact_by_tool: Dict[str, str] = {}
    for binding in compiler_output.get("artifact_bindings") or []:
        if not isinstance(binding, dict):
            continue
        accepted = str(binding.get("accepted_producer") or "")
        if accepted:
            artifact_by_tool[accepted] = str(binding.get("artifact_id") or "")
        for rejected in binding.get("rejected_producers") or []:
            if isinstance(rejected, dict) and rejected.get("tool"):
                artifact_by_tool[str(rejected["tool"])] = str(binding.get("artifact_id") or "")

    rows: List[Dict[str, Any]] = []
    for tool, hint in sorted(hint_map.items(), key=lambda item: (item[1].get("first_index", 0), item[0])):
        rejected = rejected_by_tool.get(tool)
        row = {
            "tool": tool,
            "intents": hint.get("intents") or [],
            "confidence": hint.get("confidence"),
            "source": hint.get("source"),
            "decision": "rejected" if rejected else ("accepted" if tool in final_tools else "suggested_only"),
            "reason": (rejected or {}).get("reason") or hint.get("reason", ""),
            "final_tool_call_index": final_tools.index(tool) if tool in final_tools else None,
            "artifact_id": artifact_by_tool.get(tool, ""),
        }
        rows.append({key: value for key, value in row.items() if value not in (None, "", [], {})})
    for index, tool in enumerate(final_tools):
        if tool in hint_map:
            continue
        rows.append(
            {
                "tool": tool,
                "confidence": 1.0,
                "source": "compiler_required",
                "decision": "compiler_added",
                "reason": "added by compiler/workflow/source contract",
                "final_tool_call_index": index,
                "artifact_id": artifact_by_tool.get(tool, ""),
            }
        )
    return rows


def _merge_hint(
    hint_map: Dict[str, Dict[str, Any]],
    tool: str,
    intent: Any,
    confidence: float,
    source: str,
    reason: str,
) -> None:
    tool = str(tool or "").strip()
    if not tool:
        return
    if tool not in hint_map:
        hint_map[tool] = {
            "intents": [],
            "confidence": confidence,
            "source": source,
            "reason": reason,
            "first_index": len(hint_map),
        }
    else:
        hint_map[tool]["confidence"] = max(float(hint_map[tool].get("confidence") or 0.0), float(confidence or 0.0))
        if source != "legacy_default":
            hint_map[tool]["source"] = source
    intent_text = str(intent or "").strip()
    if intent_text and intent_text not in hint_map[tool]["intents"]:
        hint_map[tool]["intents"].append(intent_text)


def _session_context_snapshot(state: ResumeQAState) -> Dict[str, Any]:
    before = state.session_context or {}
    after = state.updated_session_context or before
    return {
        "before_keys": sorted(before.keys()),
        "after_keys": sorted(after.keys()),
        "current": {
            key: after.get(key)
            for key in [
                "last_user_question",
                "last_intent",
                "last_candidate_name",
                "last_candidate_id",
                "last_candidate_pool_names",
                "last_candidate_pool_ids",
                "last_ranking_candidate_names",
                "last_ranking_candidate_ids",
            ]
            if key in after
        },
    }


def _trace_graph(state: ResumeQAState) -> Dict[str, Any]:
    nodes = [
        {"id": "router", "label": "router", "kind": "router"},
        {"id": "condition_normalizer", "label": "condition normalizer", "kind": "router"},
        {"id": "execution_policy", "label": "execution policy", "kind": "router"},
        {"id": "planner", "label": "planner", "kind": "planner"},
        {"id": "plan_compiler", "label": "plan compiler", "kind": "planner"},
        {"id": "plan_validator", "label": "plan validator", "kind": "validator"},
        {"id": "plan_repair", "label": "plan repair", "kind": "planner"},
        {"id": "executor", "label": "executor", "kind": "executor"},
        {"id": "execution_validator", "label": "execution validator", "kind": "validator"},
        {"id": "execution_repair", "label": "execution repair", "kind": "planner"},
        {"id": "aggregator", "label": "aggregator", "kind": "answer"},
        {"id": "answer_validator", "label": "answer validator", "kind": "validator"},
        {"id": "answer_rewrite", "label": "answer rewrite", "kind": "answer"},
        {"id": "rule_answer_fallback", "label": "rule answer fallback", "kind": "answer"},
        {"id": "clarification", "label": "clarification", "kind": "terminal"},
        {"id": "fail", "label": "fail", "kind": "terminal"},
        {"id": "final", "label": "final", "kind": "terminal"},
    ]
    edges = [
        {"from": "router", "to": "condition_normalizer"},
        {"from": "condition_normalizer", "to": "execution_policy"},
        {"from": "execution_policy", "to": "planner", "label": "generic"},
        {"from": "execution_policy", "to": "plan_compiler", "label": "template"},
        {"from": "planner", "to": "plan_compiler"},
        {"from": "plan_compiler", "to": "plan_validator"},
        {"from": "plan_validator", "to": "executor", "label": "ok"},
        {"from": "plan_validator", "to": "plan_repair", "label": "repair"},
        {"from": "plan_validator", "to": "clarification", "label": "clarify"},
        {"from": "plan_validator", "to": "fail", "label": "fail"},
        {"from": "plan_repair", "to": "plan_validator"},
        {"from": "executor", "to": "execution_validator"},
        {"from": "execution_validator", "to": "aggregator", "label": "ok"},
        {"from": "execution_validator", "to": "execution_repair", "label": "repair"},
        {"from": "execution_validator", "to": "clarification", "label": "clarify"},
        {"from": "execution_validator", "to": "fail", "label": "fail"},
        {"from": "execution_repair", "to": "plan_validator"},
        {"from": "aggregator", "to": "answer_validator"},
        {"from": "answer_validator", "to": "final", "label": "ok"},
        {"from": "answer_validator", "to": "answer_rewrite", "label": "rewrite"},
        {"from": "answer_validator", "to": "rule_answer_fallback", "label": "fallback"},
        {"from": "answer_validator", "to": "fail", "label": "fail"},
        {"from": "answer_rewrite", "to": "answer_validator"},
        {"from": "rule_answer_fallback", "to": "answer_validator"},
    ]
    visited = [str(item.get("node")) for item in state.trace.decision_log if item.get("node")]
    active_edges = [
        {"from": left, "to": right}
        for left, right in zip(visited, visited[1:])
    ]
    status: Dict[str, str] = {}
    for item in state.trace.decision_log:
        node = str(item.get("node") or "")
        if not node:
            continue
        output = item.get("output") or {}
        if node in {"plan_repair", "execution_repair", "answer_rewrite", "rule_answer_fallback"}:
            status[node] = "repair"
        elif node == "clarification":
            status[node] = "clarification"
        elif node == "final":
            status[node] = "final"
        elif node == "fail" or output.get("ok") is False:
            status[node] = "failed"
        else:
            status[node] = "ok"
    visited_set = set(visited)
    active_node_ids = [node["id"] for node in nodes if node["id"] in visited_set]
    active_edges = [
        edge
        for edge in active_edges
        if edge["from"] in visited_set and edge["to"] in visited_set
    ]
    return {
        "nodes": [node for node in nodes if node["id"] in visited_set],
        "edges": [edge for edge in edges if edge["from"] in visited_set and edge["to"] in visited_set],
        "visited": visited,
        "active_edges": active_edges,
        "node_status": {node_id: status.get(node_id, "ok") for node_id in active_node_ids},
    }
