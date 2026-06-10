"""Rule fallback internal data structures.

Read this file last. These dataclasses are private to the deterministic rule
draft path: signals.py fills RouterSignals, rules.py accumulates IntentDraft,
and handlers share RuleContext.

This module contains no business logic.

中文阅读提示：
这个文件只放 rule fallback 的内部数据结构，不放业务判断。
RouterSignals 是 signals.py 侦察出来的信号；
IntentDraft 是 rules.py 的 handler 临时累积器；
RuleContext 是传给每个 handler 的只读上下文。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from resume_query_ai_qa.core.config import ResumeQAConfig
from resume_query_ai_qa.core.schemas import ContextPolicy, QueryCondition


@dataclass
class RouterSignals:
    """Text signals detected before rule handlers infer draft intents.

    中文：
    文本信号集合。它只描述“问题里有什么迹象”，不代表最终 intent。
    """

    # Candidate/task shape signals.
    # 中文：候选人和任务形态信号。
    pair_compare: bool = False
    candidate_reference: bool = False

    # Multi-turn context signal resolved from router_rules context config.
    # 中文：多轮上下文指代信号，由 router_rules 的 context 配置解析。
    context_policy: ContextPolicy = field(default_factory=ContextPolicy)
    context_single_reference: bool = False
    context_pair_reference: bool = False
    context_pool_reference: bool = False

    # Intent trigger families used by rule handlers.
    # 中文：给 rules.py handler 使用的 intent 触发信号族。
    discovery: bool = False
    project_listing: bool = False
    evidence_locator: bool = False
    single_candidate_fit: bool = False
    context_pool_priority: bool = False
    interview_question: bool = False
    sensitive_interview: bool = False


@dataclass
class IntentDraft:
    """Mutable accumulator used while rule handlers add sub-intents.

    中文：
    规则 handler 的临时草稿容器。handler 只往这里追加 sub_intent、证据和
    requires_* 提示，最后再组装成 RouterOutput。
    """

    sub_intents: list[str] = field(default_factory=list)
    evidence_by_intent: dict[str, list[str]] = field(default_factory=dict)
    requires_jd: bool = False
    requires_evidence: bool = False

    def add(self, intent: str, evidence: list[str]) -> None:
        """Append one sub-intent and record trigger evidence if present.

        中文：
        添加一个子 intent；如果有触发词/条件证据，也一并记录。
        """
        self.sub_intents.append(intent)
        if evidence:
            self.evidence_by_intent[intent] = evidence


@dataclass(frozen=True)
class RuleContext:
    """Read-only context shared by rule handlers.

    中文：
    Rule handlers 共享的只读上下文，避免每个 handler 重复传长参数。
    """

    text: str
    conditions: list[QueryCondition]
    signals: RouterSignals
    config: ResumeQAConfig
