from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


IntentName = Literal[
    "candidate_count",
    "candidate_list",
    "candidate_filter",
    "candidate_profile_intro",
    "candidate_compare_pair",
    "candidate_ranking",
    "jd_scoring",
    "evidence_question",
    "interview_question_generation",
    "follow_up",
    "compound",
    "out_of_scope",
]

EvidenceStrength = Literal[
    "project_evidence",
    "project_tags",
    "domain_tags",
    "candidate_tags",
    "work_experiences",
    "education_experiences",
]


class EvidenceRef(BaseModel):
    """工具证据引用契约；连接 tool result、answer claim 和 answer validator。"""
    source_type: EvidenceStrength
    resume_identity: str = ""
    candidate_name: str = ""
    project_id: str = ""
    project_title: str = ""
    evidence_id: str = ""
    text: str = ""
    summary: str = ""
    strength: int = 0


class CandidateBrief(BaseModel):
    """候选人摘要契约；工具返回和聚合展示共用，不承载筛选或排序规则。"""
    resume_identity: str
    name: str = ""
    job_intent: str = ""
    location_raw: str = ""
    skills: List[str] = Field(default_factory=list)
    domains: List[str] = Field(default_factory=list)
    work_count: int = 0
    project_count: int = 0
    evidence_refs: List[EvidenceRef] = Field(default_factory=list)


class JDScoringCriteria(BaseModel):
    """JD 评分条件契约；scoring 工具消费它，本轮不接管 JD 规则来源。"""
    source: Literal["user_jd", "default_jd", "manual"] = "default_jd"
    target_role: str = ""
    required_domains: List[str] = Field(default_factory=list)
    required_skills: List[str] = Field(default_factory=list)
    preferred_skills: List[str] = Field(default_factory=list)
    experience_signals: List[str] = Field(default_factory=list)
    risk_signals: List[str] = Field(default_factory=list)
    scoring_weights: Dict[str, float] = Field(default_factory=dict)


class CandidateScore(BaseModel):
    """候选人评分结果契约；ranking/answer 只消费分数和证据，不重算评分。"""
    resume_identity: str
    name: str = ""
    total_score: float = 0.0
    dimension_scores: Dict[str, float] = Field(default_factory=dict)
    strengths: List[str] = Field(default_factory=list)
    risks: List[str] = Field(default_factory=list)
    evidence_refs: List[EvidenceRef] = Field(default_factory=list)
    missing_info: List[str] = Field(default_factory=list)
    recommendation_reason: str = ""
    tie_break_reason: str = ""


class ToolCallSpec(BaseModel):
    """单个可执行工具调用。

    只允许由 compiler/repair 生成，executor 按它调用 registry 中的只读工具。
    `depends_on` 和 `output_key` 用来表达工具之间的依赖和数据引用。
    """

    name: str
    arguments: Dict[str, Any] = Field(default_factory=dict)
    purpose: str = ""
    expected_output: str = ""
    output_key: str = ""
    depends_on: List[str] = Field(default_factory=list)


class ToolHint(BaseModel):
    """语义规划阶段的工具建议。

    LLM or policy 可以提出 hint，但 hint 不是可执行命令；generic compiler 会
    按 tool_policy 和 registry 决定是否接受。
    """

    name: str
    confidence: float = 0.5
    reason: str = ""
    source: Literal["llm", "router", "template", "repair", "compiler_required", "policy"] = "llm"
    scenario: str = ""


class ArtifactBinding(BaseModel):
    """工具产物绑定协议。

    用来说明 candidate_pool、candidate_count、ranked_candidates 等产物来自
    哪个 source，后续谁消费它。它的核心价值是防止 count/list/rank/evidence
    使用不同候选池。
    """

    artifact_id: str
    artifact_type: Literal[
        "candidate_collection",
        "candidate_count",
        "candidate_profile",
        "evidence_collection",
        "scored_candidates",
        "ranked_candidates",
    ]
    required_scope: Dict[str, Any] = Field(default_factory=dict)
    accepted_producer: str = ""
    accepted_scope: Dict[str, Any] = Field(default_factory=dict)
    rejected_producers: List[Dict[str, Any]] = Field(default_factory=list)
    consumers: List[str] = Field(default_factory=list)
    source_artifact_id: str = ""
    candidate_id_refs: List[str] = Field(default_factory=list)


class SubIntentEvidence(BaseModel):
    """router 复合意图证据；解释子 intent 为什么被纳入 compound。"""
    intent: IntentName
    evidence: List[str] = Field(default_factory=list)
    reason: str = ""


class ScenarioDecision(BaseModel):
    """Router 对单个 intent 的执行语义判断。"""

    scenario: str
    confidence: float = 0.5
    evidence: List[str] = Field(default_factory=list)
    reason: str = ""
    source: Literal["llm", "rule_fallback"] = "llm"


class QueryCondition(BaseModel):
    """router/condition extractor 的原始条件；后续必须经 core rules 归一化。"""
    type: str = ""
    raw_value: str = ""
    evidence: str = ""
    reason: str = ""

    @field_validator("type", "raw_value", "evidence", "reason", mode="before")
    @classmethod
    def coerce_text_field(cls, value: Any) -> str:
        """转换文本字段并返回。"""
        if isinstance(value, list):
            return " ".join(str(item) for item in value if str(item).strip())
        return str(value or "")


class NormalizedCondition(BaseModel):
    """公共规则归一化后的条件；compiler/tools 共用它生成 query/filter 参数。"""
    type: str = ""
    raw_value: str = ""
    normalized_value: str = ""
    evidence: str = ""
    matched_by: str = ""
    confidence: float = 0.0
    retrieval_terms: List[str] = Field(default_factory=list)

    @field_validator("type", "raw_value", "normalized_value", "evidence", "matched_by", mode="before")
    @classmethod
    def coerce_text_field(cls, value: Any) -> str:
        """转换文本字段并返回。"""
        if isinstance(value, list):
            return " ".join(str(item) for item in value if str(item).strip())
        return str(value or "")

    @field_validator("retrieval_terms", mode="before")
    @classmethod
    def coerce_retrieval_terms(cls, value: Any) -> list[str]:
        """转换检索词项集合并返回。"""
        if isinstance(value, str):
            return [value]
        if isinstance(value, list):
            return [str(item) for item in value if str(item).strip()]
        return []


class ContextPolicy(BaseModel):
    """多轮上下文使用策略。

    router 用它标记“这些人/他/第一名”等表达是否依赖 session_context；
    compiler 负责把上下文绑定成 candidate_ids；validator 负责在缺上下文时
    触发 clarification。
    """

    uses_context: bool = False
    context_ref_type: Literal[
        "none",
        "candidate_pool",
        "last_candidate",
        "ranking_top",
        "ranking_top_k",
        "comparison_pair",
        "jd",
        "ambiguous",
    ] = "none"
    evidence: List[str] = Field(default_factory=list)
    reason: str = ""


class SubTaskPlan(BaseModel):
    """compound plan 的子任务契约；compiler 生成，executor 仍只执行其中 tool_calls。"""
    intent: IntentName
    tool_calls: List[ToolCallSpec] = Field(default_factory=list)
    requires_jd_criteria: bool = False
    requires_evidence: bool = False


class SemanticStep(BaseModel):
    """SemanticPlan 中的一步语义任务。

    它描述某个 intent 在某个 scenario 下需要什么条件和工具线索，但仍不是
    executor 可以执行的 ToolCallSpec。
    """

    intent: IntentName
    scenario: str = ""
    needs: List[str] = Field(default_factory=list)
    tool_hints: List[str] = Field(default_factory=list)
    tool_hint_scores: List[ToolHint] = Field(default_factory=list)
    conditions: List[NormalizedCondition] = Field(default_factory=list)
    requires_jd: bool = False
    requires_evidence: bool = False
    evidence: List[str] = Field(default_factory=list)
    reason: str = ""


class SemanticPlan(BaseModel):
    """generic 路径的语义 IR。

    planner 产出它，plan_compiler 消费它。它只回答“想做什么”，不回答
    “最终执行哪个工具参数”。
    """

    intent: IntentName
    is_compound: bool = False
    steps: List[SemanticStep] = Field(default_factory=list)
    context_policy: ContextPolicy = Field(default_factory=ContextPolicy)
    normalized_conditions: List[NormalizedCondition] = Field(default_factory=list)
    compile_strategy: Literal["domain_template", "tool_binding"] = "domain_template"
    notes: List[str] = Field(default_factory=list)

    @field_validator("compile_strategy", mode="before")
    @classmethod
    def _default_compile_strategy(cls, value: Any) -> Any:
        """获取默认compile策略并返回。"""
        if value in {None, ""}:
            return "domain_template"
        return value

    @field_validator("notes", mode="before")
    @classmethod
    def _coerce_notes(cls, value: Any) -> Any:
        """转换备注并返回。"""
        if value is None or value == "":
            return []
        if isinstance(value, str):
            return [value]
        return value


class ExecutionDecision(BaseModel):
    """execution_policy 产出的调度决策。

    runner 根据 `compiler` 决定下一跳：workflow_template 跳过 planner，
    generic_tool_binding 进入 planner。这个对象让 template/generic 分流可解释。
    """

    compiler: Literal["workflow_template", "generic_tool_binding"]
    planner: Literal["rule", "llm"] = "rule"
    workflow_name: str = ""
    scenarios: Dict[str, str] = Field(default_factory=dict)
    reason: str = ""


class PlanConstraints(BaseModel):
    """计划级硬约束；validator/answer_validator 共用，避免节点私有约束表。"""
    comparison_max_candidates: int = 2
    ranking_requires_jd_criteria: bool = True
    ranking_output_limit: int | None = None
    facts_must_come_from_tools: bool = True
    hide_contact_by_default: bool = True


class QueryPlan(BaseModel):
    """executor 唯一接受的可执行计划。

    它包含 ToolCallSpec、SubTaskPlan、ArtifactBinding 和执行约束。任何 LLM
    输出都必须先经过 compiler/validator 变成合法 QueryPlan，才能进入 executor。
    """

    intent: IntentName
    is_compound: bool = False
    sub_tasks: List[SubTaskPlan] = Field(default_factory=list)
    tool_calls: List[ToolCallSpec] = Field(default_factory=list)
    artifact_bindings: List[ArtifactBinding] = Field(default_factory=list)
    constraints: PlanConstraints = Field(default_factory=PlanConstraints)
    notes: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_compound_shape(self) -> "QueryPlan":
        """校验复合计划结构并返回校验后的对象。"""
        if self.intent == "compound" and not self.sub_tasks:
            raise ValueError("compound plans must include sub_tasks")
        if self.intent != "compound" and self.is_compound:
            raise ValueError("is_compound=true requires intent='compound'")
        return self


class RouterOutput(BaseModel):
    """router 的结构化输出。

    它是整条链路的入口协议：intent、compound、conditions、context_policy、
    evidence/JD 需求都会被后续 policy、planner、compiler、validator 消费。
    """

    intent: IntentName
    is_compound: bool = False
    sub_intent_candidates: List[IntentName] = Field(default_factory=list)
    sub_intent_evidence: List[SubIntentEvidence] = Field(default_factory=list)
    scenario_decisions: Dict[str, ScenarioDecision] = Field(default_factory=dict)
    conditions: List[QueryCondition] = Field(default_factory=list)
    normalized_conditions: List[NormalizedCondition] = Field(default_factory=list)
    context_policy: ContextPolicy = Field(default_factory=ContextPolicy)
    requires_jd: bool = False
    requires_evidence: bool = False
    allowed_tool_names: List[str] = Field(default_factory=list)
    risk_flags: List[str] = Field(default_factory=list)


class ValidationIssue(BaseModel):
    """validator 输出的结构化问题；repair 根据 code/action 规则选择下一步。"""
    category: str
    code: str
    message: str
    severity: Literal["error", "warning"] = "error"
    repairable: bool = True
    details: Dict[str, Any] = Field(default_factory=dict)


class ValidationResult(BaseModel):
    """validator 节点统一返回值；runner 只看 ok、issue 和 next_node 调度。"""
    ok: bool
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    error_details: List[ValidationIssue] = Field(default_factory=list)
    repair_hint: str = ""
    next_node: Literal[
        "plan_repair",
        "executor",
        "execution_repair",
        "aggregator",
        "answer_rewrite",
        "final",
        "clarification",
        "fail",
        "planner_node",
        "executor_node",
        "aggregator_node",
        "answer_validator_node",
        "clarification_node",
        "end",
    ] = "end"


class ToolResult(BaseModel):
    """executor 调用工具后的事实结果。

    aggregator 的所有事实都必须来自 ToolResult；answer_validator 会用它复核
    count/name/ranking/evidence claim。
    """

    tool_name: str
    ok: bool = True
    data: Any = None
    error: str = ""
    warnings: List[str] = Field(default_factory=list)


class AnswerClaim(BaseModel):
    """答案声明契约；answer_validator 用它复核 count/name/ranking/evidence。"""
    text: str
    claim_type: Literal["count", "name", "ranking", "comparison", "evidence", "profile", "other"] = "other"
    supported_by: List[str] = Field(default_factory=list)
    subject: str = ""
    value: Any = None
    evidence_ids: List[str] = Field(default_factory=list)


class AggregatedAnswer(BaseModel):
    """aggregator/rewrite 的最终答案契约；文本、claims、evidence refs 必须同步。"""
    answer: str = ""
    claims: List[AnswerClaim] = Field(default_factory=list)
    used_evidence_refs: List[EvidenceRef] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


class RetryCounts(BaseModel):
    """运行内 retry 计数；节点只更新计数，不自行决定全局 retry 上限。"""
    router: int = 0
    planner: int = 0
    executor_tool_call: int = 0
    aggregator_rewrite: int = 0


class ResumeQATrace(BaseModel):
    """一次 QA 运行的审计轨迹。

    前端 Debug、API trace summary、后端 detail JSON 都围绕这个对象展开。
    每个 node 会把关键输入输出和 fallback/repair 信息写入 decision_log。
    """

    trace_id: str = ""
    deep_debug: bool = False
    decision_log: List[Dict[str, Any]] = Field(default_factory=list)
    node_events: List[Dict[str, Any]] = Field(default_factory=list)
    route_events: List[Dict[str, Any]] = Field(default_factory=list)
    state_snapshots: List[Dict[str, Any]] = Field(default_factory=list)
    run_summary: Dict[str, Any] = Field(default_factory=dict)
    router_output: Optional[RouterOutput] = None
    execution_decision: Optional[ExecutionDecision] = None
    semantic_plan: Optional[SemanticPlan] = None
    planner_output: Optional[QueryPlan] = None
    plan_validation_errors: List[str] = Field(default_factory=list)
    tool_calls: List[ToolCallSpec] = Field(default_factory=list)
    tool_results_summary: List[str] = Field(default_factory=list)
    execution_validation_errors: List[str] = Field(default_factory=list)
    aggregator_answer: str = ""
    answer_validation_errors: List[str] = Field(default_factory=list)
    clarification_required: bool = False
    clarification_question: str = ""
    clarification_options: List[str] = Field(default_factory=list)
    updated_session_context: Dict[str, Any] = Field(default_factory=dict)
    final_status: Literal["pending", "ok", "failed", "needs_clarification"] = "pending"


class ResumeQAState(BaseModel):
    """LangGraph 运行态契约；串起 router、policy、planner、executor、answer 全链路。"""
    question: str
    session_context: Dict[str, Any] = Field(default_factory=dict)
    intent: Optional[IntentName] = None
    sub_tasks: List[SubTaskPlan] = Field(default_factory=list)
    plan: Optional[QueryPlan] = None
    plan_errors: List[str] = Field(default_factory=list)
    tool_results: List[ToolResult] = Field(default_factory=list)
    execution_errors: List[str] = Field(default_factory=list)
    answer: Optional[AggregatedAnswer] = None
    answer_errors: List[str] = Field(default_factory=list)
    clarification_required: bool = False
    clarification_question: str = ""
    clarification_options: List[str] = Field(default_factory=list)
    updated_session_context: Dict[str, Any] = Field(default_factory=dict)
    retry_count: RetryCounts = Field(default_factory=RetryCounts)
    trace: ResumeQATrace = Field(default_factory=ResumeQATrace)
