"""Rule fallback internal data structures.

Read this file last. These dataclasses are private to the deterministic rule
draft path: signals.py fills RouterSignals, rules.py accumulates IntentDraft,
and handlers share RuleContext.

This module contains no business logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from resume_query_ai_qa.core.config import ResumeQAConfig
from resume_query_ai_qa.core.schemas import ContextPolicy, QueryCondition


@dataclass
class RouterSignals:
    """Text signals detected before rule handlers infer draft intents."""

    # Candidate/task shape signals.
    pair_compare: bool = False
    candidate_reference: bool = False

    # Multi-turn context signal resolved from router_rules context config.
    context_policy: ContextPolicy = field(default_factory=ContextPolicy)
    context_single_reference: bool = False
    context_pair_reference: bool = False
    context_pool_reference: bool = False

    # Intent trigger families used by rule handlers.
    discovery: bool = False
    project_listing: bool = False
    evidence_locator: bool = False
    single_candidate_fit: bool = False
    context_pool_priority: bool = False
    interview_question: bool = False
    sensitive_interview: bool = False


@dataclass
class IntentDraft:
    """Mutable accumulator used while rule handlers add sub-intents."""

    sub_intents: list[str] = field(default_factory=list)
    evidence_by_intent: dict[str, list[str]] = field(default_factory=dict)
    requires_jd: bool = False
    requires_evidence: bool = False

    def add(self, intent: str, evidence: list[str]) -> None:
        """Append one sub-intent and record trigger evidence if present."""
        self.sub_intents.append(intent)
        if evidence:
            self.evidence_by_intent[intent] = evidence


@dataclass(frozen=True)
class RuleContext:
    """Rule handlers 共享的只读上下文，避免每个 handler 重复传长参数。"""

    text: str
    conditions: list[QueryCondition]
    signals: RouterSignals
    config: ResumeQAConfig
