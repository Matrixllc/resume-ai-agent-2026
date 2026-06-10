from __future__ import annotations

import re
from typing import Any, Dict, List, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from resume_query_ai_qa.core.schemas import CandidateScore, EvidenceRef, ResumeQAState
from resume_query_ai_qa.graph import run

router = APIRouter(prefix="/qa", tags=["qa"])


class QAAskRequest(BaseModel):
    question: str
    session_context: Dict[str, Any] = Field(default_factory=dict)
    use_llm: bool = True
    debug: bool = False


class QAAskResponse(BaseModel):
    status: Literal["ok", "needs_clarification", "failed"]
    answer: str = ""
    clarification_required: bool = False
    clarification_question: str = ""
    clarification_options: List[str] = Field(default_factory=list)
    used_evidence_refs: List[Dict[str, Any]] = Field(default_factory=list)
    ranking: List[Dict[str, Any]] = Field(default_factory=list)
    comparison_profiles: List[Dict[str, Any]] = Field(default_factory=list)
    comparison_candidate_ids: List[str] = Field(default_factory=list)
    updated_session_context: Dict[str, Any] = Field(default_factory=dict)
    trace: Dict[str, Any] | None = None


@router.post("/ask", response_model=QAAskResponse)
def ask_resume_qa(request: QAAskRequest, debug: bool | None = None) -> QAAskResponse:
    question = request.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="question is required")
    state = run(
        question,
        session_context=request.session_context,
        use_llm=request.use_llm,
        debug_trace=request.debug if debug is None else debug,
    )
    return _response_from_state(state, debug=request.debug if debug is None else debug)


def _response_from_state(state: ResumeQAState, *, debug: bool) -> QAAskResponse:
    answer = state.answer.answer if state.answer else ""
    status = state.trace.final_status
    if status not in {"ok", "needs_clarification", "failed"}:
        status = "failed"
    trace = _trace_summary(state) if debug else _public_trace_summary(state)
    return QAAskResponse(
        status=status,
        answer=answer,
        clarification_required=state.clarification_required,
        clarification_question=state.clarification_question,
        clarification_options=state.clarification_options,
        used_evidence_refs=_used_evidence_refs(state),
        ranking=_ranking_from_state(state),
        comparison_profiles=_comparison_profiles(state),
        comparison_candidate_ids=_comparison_candidate_ids(state),
        updated_session_context=state.updated_session_context or state.session_context,
        trace=trace,
    )


def _ranking_from_state(state: ResumeQAState) -> List[Dict[str, Any]]:
    for result in reversed(state.tool_results):
        if not result.ok or result.tool_name != "rank_candidates":
            continue
        scores = result.data or []
        return [
            (item if isinstance(item, CandidateScore) else CandidateScore.model_validate(item)).model_dump()
            for item in scores
        ]
    return []


def _comparison_candidate_ids(state: ResumeQAState) -> List[str]:
    for result in reversed(state.tool_results):
        if not result.ok or result.tool_name != "build_comparison_pack" or not isinstance(result.data, dict):
            continue
        return [str(item) for item in result.data.get("candidate_ids", []) if str(item).strip()]
    return []


def _comparison_profiles(state: ResumeQAState) -> List[Dict[str, Any]]:
    for result in reversed(state.tool_results):
        if not result.ok or result.tool_name != "build_comparison_pack" or not isinstance(result.data, dict):
            continue
        candidate_ids = [str(item) for item in result.data.get("candidate_ids", []) if str(item).strip()]
        profiles = result.data.get("profiles", {})
        if not isinstance(profiles, dict):
            return []
        output: List[Dict[str, Any]] = []
        for candidate_id in candidate_ids:
            profile = profiles.get(candidate_id, {})
            if not isinstance(profile, dict):
                continue
            output.append(
                {
                    "resume_identity": candidate_id,
                    "name": profile.get("name", ""),
                    "job_intent": profile.get("job_intent", ""),
                    "work_experiences": profile.get("work_experiences", []),
                    "projects": profile.get("projects", []),
                }
            )
        return output
    return []


def _used_evidence_refs(state: ResumeQAState) -> List[Dict[str, Any]]:
    refs: List[EvidenceRef] = []
    if state.answer:
        refs.extend(state.answer.used_evidence_refs)
    if not refs:
        refs.extend(_evidence_from_tool_results(state))
    seen: set[str] = set()
    output: List[Dict[str, Any]] = []
    for ref in refs:
        key = ref.evidence_id or f"{ref.resume_identity}:{ref.project_id}:{ref.text[:40]}"
        if key in seen:
            continue
        seen.add(key)
        output.append(_with_evidence_summary(ref).model_dump())
    return output


def _evidence_from_tool_results(state: ResumeQAState) -> List[EvidenceRef]:
    refs: List[EvidenceRef] = []
    for result in state.tool_results:
        if not result.ok:
            continue
        refs.extend(_extract_evidence_refs(result.data))
    return refs


def _extract_evidence_refs(value: Any) -> List[EvidenceRef]:
    refs: List[EvidenceRef] = []
    if isinstance(value, EvidenceRef):
        return [value]
    if isinstance(value, CandidateScore):
        return list(value.evidence_refs)
    if hasattr(value, "model_dump"):
        return _extract_evidence_refs(value.model_dump())
    if isinstance(value, dict):
        if _looks_like_evidence_ref(value):
            try:
                return [EvidenceRef.model_validate(value)]
            except Exception:
                return []
        for item in value.values():
            refs.extend(_extract_evidence_refs(item))
    elif isinstance(value, list):
        for item in value:
            refs.extend(_extract_evidence_refs(item))
    return refs


def _looks_like_evidence_ref(value: Dict[str, Any]) -> bool:
    return bool({"source_type", "resume_identity", "evidence_id"} & set(value))


def _with_evidence_summary(ref: EvidenceRef) -> EvidenceRef:
    if ref.summary.strip():
        return ref
    subject = ref.candidate_name or "候选人"
    title = ref.project_title or _source_label(ref.source_type)
    text = _clean_evidence_text(ref.text, title)
    if text:
        first = _first_sentence(text)
        summary = f"{subject}在{title}中体现：{first}"
    else:
        summary = f"{subject}的{title}可作为该结论的来源，但原始证据文本较少。"
    if len(summary) > 80:
        summary = summary[:77].rstrip("，。；、 ") + "..."
    return ref.model_copy(update={"summary": summary})


def _first_sentence(text: str) -> str:
    for separator in ["。", "；", ";", "\n"]:
        if separator in text:
            head = text.split(separator, 1)[0].strip()
            if head:
                return head
    return text.strip()


def _clean_evidence_text(value: str, title: str = "") -> str:
    text = " ".join((value or "").replace("\n", " ").split())
    text = re.sub(r"^#+\s*", "", text)
    text = re.sub(r"^[-•●\s]+", "", text)
    if title:
        clean_title = " ".join(title.split())
        for prefix in [clean_title, f"{clean_title} -", f"{clean_title}：", f"{clean_title}:"]:
            if text.startswith(prefix):
                text = text[len(prefix):].strip(" -：:")
                break
    text = re.sub(r"\s*[-•●]\s*", "，", text)
    return " ".join(text.split())


def _source_label(source_type: str) -> str:
    return {
        "project_evidence": "项目证据",
        "project_tags": "项目标签",
        "domain_tags": "领域标签",
        "candidate_tags": "候选人标签",
        "work_experiences": "工作经历",
        "education_experiences": "教育经历",
    }.get(str(source_type), "证据")


def _trace_summary(state: ResumeQAState) -> Dict[str, Any]:
    log_hint = f"resume_query_ai_qa/logs/*{state.trace.trace_id}*.json" if state.trace.trace_id else ""
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
        "input": {},
        "decision": _strip_empty(
            {
                "engine": item.get("engine"),
                "fallback_reason": item.get("fallback_reason"),
                "duration_ms": item.get("duration_ms"),
            }
        ),
        "output": {},
        "raw": _compact_value(output, max_items=6),
    }

    if node == "router":
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
                    "sub_intent_candidates": output.get("sub_intent_candidates"),
                    "scenario_decisions": output.get("scenario_decisions"),
                    "context_policy": output.get("context_policy"),
                    "requires_jd": output.get("requires_jd"),
                    "requires_evidence": output.get("requires_evidence"),
                }
            ),
            "output": _strip_empty(
                {
                    "conditions": output.get("conditions"),
                    "risk_flags": output.get("risk_flags"),
                }
            ),
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
                    "ref_bindings": output.get("ref_bindings"),
                    "artifact_bindings": compiled_plan.get("artifact_bindings"),
                }
            ),
            "output": {"tool_calls": _compiled_plan_tool_calls(compiled_plan)},
        }

    if node == "plan_validator":
        return {
            **base,
            "input": {"compiled_tool_calls": _compiled_plan_tool_calls(compiled_plan)},
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
            "input": {"tool_calls": calls},
            "decision": {"depends_on": [{call.get("name"): call.get("depends_on") or []} for call in calls]},
            "output": {"tool_results": _tool_result_summaries(state)},
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
                    "used_evidence_count": output.get("used_evidence_count"),
                }
            ),
        }

    if node == "answer_validator":
        answer = state.answer.model_dump() if state.answer else {}
        return {
            **base,
            "input": _strip_empty(
                {
                    "claim_count": len(answer.get("claims") or []),
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


def _result_shape(value: Any) -> str:
    if hasattr(value, "model_dump"):
        return type(value).__name__
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "dict"
    if value is None:
        return "none"
    return type(value).__name__


def _result_count(value: Any) -> int | None:
    if isinstance(value, (list, tuple, set, dict)):
        return len(value)
    return None


def _plan_requires_evidence(state: ResumeQAState) -> bool:
    if state.trace.router_output and state.trace.router_output.requires_evidence:
        return True
    plan = state.plan
    if not plan:
        return False
    return bool(
        any(getattr(sub_task, "requires_evidence", False) for sub_task in plan.sub_tasks)
    )


def _compact_value(value: Any, *, max_items: int = 5) -> Any:
    if hasattr(value, "model_dump"):
        return _compact_value(value.model_dump(), max_items=max_items)
    if isinstance(value, dict):
        output: Dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= max_items:
                output["__truncated__"] = f"+{len(value) - max_items}"
                break
            output[str(key)] = _compact_value(item, max_items=max_items)
        return output
    if isinstance(value, list):
        output = [_compact_value(item, max_items=max_items) for item in value[:max_items]]
        if len(value) > max_items:
            output.append({"__truncated__": f"+{len(value) - max_items}"})
        return output
    if isinstance(value, tuple):
        return _compact_value(list(value), max_items=max_items)
    text = str(value)
    return text[:300] + "..." if len(text) > 300 else value


def _diagnosis_summary(state: ResumeQAState, *, include_lookup: bool = True) -> Dict[str, Any]:
    validation = {
        "plan": list(state.trace.plan_validation_errors or []),
        "execution": list(state.trace.execution_validation_errors or []),
        "answer": list(state.trace.answer_validation_errors or []),
    }
    failed_route = _last_route_to(state, {"fail", "clarify", "fallback", "repair"})
    failed_step = _last_problem_step(state)
    fallback_steps = [
        _strip_empty(
            {
                "node": item.get("node", ""),
                "fallback_reason": item.get("fallback_reason", ""),
                "repair_action": (item.get("output") or {}).get("repair_action", "") if isinstance(item.get("output"), dict) else "",
                "repair_reason": (item.get("output") or {}).get("repair_reason", "") if isinstance(item.get("output"), dict) else "",
                "error_category": (item.get("output") or {}).get("error_category", "") if isinstance(item.get("output"), dict) else "",
            }
        )
        for item in state.trace.decision_log
        if item.get("fallback_reason")
        or (isinstance(item.get("output"), dict) and ((item.get("output") or {}).get("repair_action") or (item.get("output") or {}).get("error_category")))
    ]
    tool_failures = [
        {"tool": result.tool_name, "error": result.error}
        for result in state.tool_results
        if not result.ok
    ]
    warnings = _collect_warnings(state)
    reason = _first_non_empty(
        (failed_route or {}).get("reason", ""),
        (failed_step or {}).get("reason", ""),
        validation["plan"][0] if validation["plan"] else "",
        validation["execution"][0] if validation["execution"] else "",
        validation["answer"][0] if validation["answer"] else "",
        tool_failures[0]["error"] if tool_failures else "",
    )
    status = state.trace.final_status or "failed"
    if status == "ok" and fallback_steps:
        level = "warning"
    elif status == "ok" and warnings:
        level = "info"
    elif status == "needs_clarification":
        level = "clarification"
    elif status == "failed":
        level = "error"
    else:
        level = "ok"
    return _strip_empty(
        {
            "level": level,
            "status": status,
            "headline": _diagnosis_headline(status, reason, fallback_steps, warnings),
            "impact": _diagnosis_impact(status, fallback_steps),
            "handling": _diagnosis_handling(status, fallback_steps),
            "suggested_check": _diagnosis_suggested_check((failed_step or {}).get("node", ""), validation, fallback_steps, warnings),
            "technical_code": reason,
            "failed_node": (failed_step or {}).get("node", ""),
            "failed_reason": reason,
            "route_from": (failed_route or {}).get("route_from", ""),
            "route_to": (failed_route or {}).get("route_to", ""),
            "route_reason": (failed_route or {}).get("reason", ""),
            "fallbacks": fallback_steps,
            "tool_failures": tool_failures,
            "warnings": warnings[:8],
            "validation_errors": {key: value for key, value in validation.items() if value},
            "trace_lookup": f"trace_id={state.trace.trace_id}; detail=resume_query_ai_qa/logs/*{state.trace.trace_id}*.json" if include_lookup and state.trace.trace_id else "",
        }
    )


def _last_route_to(state: ResumeQAState, route_targets: set[str]) -> Dict[str, Any]:
    for item in reversed(state.trace.route_events):
        if str(item.get("route_to") or "") in route_targets:
            return item
    return {}


def _last_problem_step(state: ResumeQAState) -> Dict[str, Any]:
    for item in reversed(state.trace.decision_log):
        output = item.get("output") if isinstance(item.get("output"), dict) else {}
        errors = output.get("errors") or []
        if output.get("ok") is False or errors or output.get("error_category"):
            return {
                "node": item.get("node", ""),
                "reason": output.get("error_category") or "; ".join(str(error) for error in errors[:2]),
            }
    return {}


def _collect_warnings(state: ResumeQAState) -> List[str]:
    warnings: List[str] = []
    if state.answer:
        warnings.extend(str(item) for item in state.answer.warnings if str(item).strip())
    for result in state.tool_results:
        warnings.extend(str(item) for item in result.warnings if str(item).strip())
    for item in state.trace.decision_log:
        output = item.get("output") if isinstance(item.get("output"), dict) else {}
        warnings.extend(str(item) for item in output.get("warnings", []) if str(item).strip())
    return list(dict.fromkeys(warnings))


def _diagnosis_headline(status: str, reason: str, fallback_steps: List[Dict[str, Any]], warnings: List[str]) -> str:
    if status == "failed":
        return f"失败：{reason or '查看 validation_errors 和 route_events'}"
    if status == "needs_clarification":
        return f"需要澄清：{reason or '缺少上下文或比较对象'}"
    if fallback_steps:
        return "已完成，但发生 fallback/repair，请查看 fallbacks。"
    if warnings:
        return "已完成，存在可解释 warning。"
    return "已完成，主链路未记录失败或 fallback。"


def _diagnosis_impact(status: str, fallback_steps: List[Dict[str, Any]]) -> str:
    if status in {"failed", "needs_clarification"}:
        return "本轮没有生成可作为最终结果使用的已校验答案。"
    if fallback_steps:
        return "最终答案已重新通过校验，中间异常输出未直接交付。"
    return "未发现影响最终答案可信度的问题。"


def _diagnosis_handling(status: str, fallback_steps: List[Dict[str, Any]]) -> str:
    if status in {"failed", "needs_clarification"}:
        return "系统停止链路并保留诊断，没有静默生成未经校验的答案。"
    if fallback_steps:
        return "系统丢弃或修复不可用的中间结果，并重新进入 validator。"
    return "系统按正常路径完成执行和校验。"


def _diagnosis_suggested_check(
    node: str,
    validation: Dict[str, List[str]],
    fallback_steps: List[Dict[str, Any]],
    warnings: List[str],
) -> str:
    target = node or str((fallback_steps[-1] if fallback_steps else {}).get("node") or "")
    if validation.get("answer") or target in {"aggregator", "answer_validator", "answer_rewrite", "rule_answer_fallback"}:
        return "检查 aggregator grounded context、answer layout、claims 和 answer validator。"
    if validation.get("execution") or target in {"executor", "execution_validator", "execution_repair"}:
        return "检查工具参数、工具结果、候选池 lineage 和 execution validator。"
    if warnings and all(str(item).startswith("answer_layout") for item in warnings):
        return "这是答案布局审计信息；如需调整展示，检查 answer_layouts.yaml。"
    if not target and not any(validation.values()):
        return "无需处理；可使用 trace_id 查看完整执行记录。"
    return "检查 Router intent/scenario、compiler template、tool policy 和 plan validator。"


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


def _first_non_empty(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _strip_empty(data: Dict[str, Any]) -> Dict[str, Any]:
    return {key: value for key, value in data.items() if value not in (None, "", [], {})}


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
