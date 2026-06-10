"""Compact JSON contracts for local structured-output fallback."""

from __future__ import annotations

import json
from typing import Type

from pydantic import BaseModel


def compact_json_contract(schema: Type[BaseModel]) -> str:
    """精简JSON合同并返回。"""
    name = schema.__name__
    if name == "AggregatedAnswer":
        return json.dumps(
            {
                "answer": "string",
                "claims": [
                    {
                        "text": "string",
                        "claim_type": "count|name|ranking|comparison|evidence|profile|other",
                        "supported_by": ["tool_name"],
                        "subject": "candidate name or empty string",
                        "value": "number|string|object|null",
                        "evidence_ids": ["evidence id"],
                    }
                ],
                "used_evidence_refs": [
                    {
                        "source_type": "project_evidence|project_tags|domain_tags|candidate_tags|work_experiences|education_experiences",
                        "resume_identity": "string",
                        "candidate_name": "string",
                        "project_id": "string",
                        "project_title": "string",
                        "evidence_id": "string",
                        "text": "string",
                        "summary": "string",
                        "strength": 0,
                    }
                ],
                "warnings": ["string"],
            },
            ensure_ascii=False,
        )
    if name == "RouterOutput":
        return json.dumps(
            {
                "intent": "candidate_count|candidate_list|candidate_filter|candidate_profile_intro|candidate_compare_pair|candidate_ranking|jd_scoring|evidence_question|interview_question_generation|follow_up|compound|out_of_scope",
                "is_compound": False,
                "sub_intent_candidates": ["intent"],
                "sub_intent_evidence": [{"intent": "intent", "evidence": ["matched query text"], "reason": "short reason"}],
                "scenario_decisions": {
                    "intent": {
                        "scenario": "soft_summary|hard_filter|open_recall|fact_check|evidence_lookup|compare_rank|out_of_scope",
                        "confidence": 0.95,
                        "evidence": ["matched query text"],
                        "reason": "why this execution scenario applies",
                        "source": "llm",
                    }
                },
                "conditions": [{"type": "domain|skill|concept|candidate_name|scope|major", "raw_value": "user text", "evidence": "matched text", "reason": "short reason"}],
                "normalized_conditions": [],
                "context_policy": {"uses_context": False, "context_ref_type": "none|candidate_pool|last_candidate|ranking_top|ranking_top_k|comparison_pair|jd|ambiguous", "evidence": [], "reason": "short reason"},
                "requires_jd": False,
                "requires_evidence": False,
                "allowed_tool_names": [],
                "risk_flags": [],
            },
            ensure_ascii=False,
        )
    if name == "QueryPlan":
        return json.dumps(
            {
                "intent": "same finite intent as router",
                "is_compound": False,
                "sub_tasks": [
                    {
                        "intent": "intent",
                        "tool_calls": [
                            {
                                "name": "allowed tool name",
                                "arguments": {},
                                "purpose": "short purpose",
                                "expected_output": "short expected output",
                                "output_key": "",
                                "depends_on": [],
                            }
                        ],
                        "requires_jd_criteria": False,
                        "requires_evidence": False,
                    }
                ],
                "tool_calls": [
                    {
                        "name": "allowed tool name",
                        "arguments": {},
                        "purpose": "short purpose",
                        "expected_output": "short expected output",
                        "output_key": "",
                        "depends_on": [],
                    }
                ],
                "constraints": {
                    "comparison_max_candidates": 2,
                    "ranking_requires_jd_criteria": True,
                    "facts_must_come_from_tools": True,
                    "hide_contact_by_default": True,
                },
                "notes": [],
            },
            ensure_ascii=False,
        )
    properties = schema.model_json_schema().get("properties", {})
    return json.dumps({key: "value" for key in properties}, ensure_ascii=False)
