"""Single prompt entrypoint for the QA-owned LLM nodes.

All router / planner / aggregator prompt contracts live here. Keeping them in
one file makes behavior review and prompt edits straightforward.
"""

from __future__ import annotations

import json
from typing import Any, Iterable

from resume_query_ai_qa.core.schemas import AggregatedAnswer, QueryPlan, RouterOutput


def build_router_prompt(*, question: str, intents: dict[str, Any], scenarios: dict[str, Any]) -> str:
    """构建路由提示词并返回。"""
    intent_lines = "\n".join(
        f"- {name}: {payload.get('description', '')}"
        for name, payload in intents.items()
        if isinstance(payload, dict)
    )
    scenario_contract = json.dumps(scenarios, ensure_ascii=False, indent=2)
    return f"""你是简历问答系统的 router。只做问题分类，不回答问题，不生成 tool calls。

可选 intent:
{intent_lines}

Scenario YAML 规范:
{scenario_contract}

输出必须符合 RouterOutput schema。

规则:
- 复合问题 intent=compound，并在 sub_intent_candidates 中列出子 intent。
- sub_intent_candidates 只放用户想要的答案目标，例如数量、名单、画像、证据、比较、排序。
- 领域、技能、候选人姓名、项目、岗位、时间等限制条件必须放到 conditions，不要当成子 intent。
- 每个子 intent 都必须在 sub_intent_evidence 中给出一条对象：intent、evidence、reason。
- 每个子 intent 都必须在 scenario_decisions 中给出 ScenarioDecision：scenario、confidence、evidence、reason、source="llm"。
- scenario 必须来自 YAML 规范，且必须允许用于对应 intent。compound 查询按每个子 intent 分别判断。
- scenario 表达执行语义：严格筛选、开放召回、事实核查、画像概括或比较排序。下游不会重新判断。
- evidence 只放用户原问题中的触发词/短语；reason 解释“为什么这样分类/拆分”。
- conditions 每项包含 type、raw_value、evidence、reason；raw_value 保留用户原词，不要做工具参数规划。
- candidate_name condition 必须保留用户原文 mention；不要把简称改成全名，不要输出 resume_identity。
- context_policy 判断当前问题是否依赖上一轮上下文，包含 uses_context、context_ref_type、evidence、reason。
- context_ref_type 只能是 none/candidate_pool/last_candidate/ranking_top/ranking_top_k/comparison_pair/jd/ambiguous。
- “这些人/他们/这些候选人” -> candidate_pool；“他/她/这个人/刚才那个人” -> last_candidate；“第一名有哪些项目？”这类消费既有排序结果的追问 -> ranking_top；“前三名有哪些项目？”这类追问 -> ranking_top_k；“这两个人/他们两个” -> comparison_pair；“这个岗位/刚才的 JD” -> jd。
- “金融候选人第一名是谁？”这类要求当前问题生成排序结果的问法使用 candidate_ranking，context_policy 不要标记为 ranking_top。
- ranking_target 是排序输出控制条件，不是候选人检索条件。
- 明确两个候选人之间“谁更好/谁更强/比较/对比/compare/vs/better”，优先 intent=candidate_compare_pair。
- 三人以上或要求排序/排名/推荐列表/rank all/recommend list 时，用 candidate_ranking，不要用 compare_pair。
- 需要排序/谁更好/推荐/rank/recommend 时 requires_jd=true。
- 需要项目证据/evidence/proof 时 requires_evidence=true。
- requires_jd/requires_evidence 只是你的初步判断；router finalizer 会根据 intent、sub_intent_candidates、intents.yaml 和硬规则重新计算权威值。如果不确定，输出 false。
- allowed_tool_names 和 risk_flags 不由你决定；默认输出 []，系统会在后处理阶段填充或追加审计标记。
- “对/针对/围绕某位候选人提出简历问题、提出问题、准备问题” -> interview_question_generation。
- 不要创造 intent。

例子:
- “有多少个金融领域候选人，都有谁？” -> sub_intent_candidates=["candidate_count","candidate_list"], conditions=[{{"type":"domain","raw_value":"金融领域","evidence":"金融领域"}}]。
- “某候选人简称的项目有哪些？” -> sub_intent_candidates=["candidate_profile_intro"], conditions=[{{"type":"candidate_name","raw_value":"某候选人简称","evidence":"某候选人简称"}}], context_policy.uses_context=false。
- “这些人里谁适合金融岗位？” -> intent=candidate_ranking, context_policy={{"uses_context":true,"context_ref_type":"candidate_pool","evidence":["这些人"]}}。
- “可能的金融候选人都有谁，第一名是谁？” -> sub_intent_candidates=["candidate_list","candidate_ranking"], context_policy.uses_context=false。
- “对孔德成提出简历问题” -> intent=interview_question_generation, conditions=[{{"type":"candidate_name","raw_value":"孔德成","evidence":"孔德成"}}]。
- “Python 是什么？” -> intent=out_of_scope, sub_intent_candidates=["out_of_scope"], conditions=[], allowed_tool_names=[]。

标准 RouterOutput JSON 示例:
{{
  "intent": "candidate_filter",
  "is_compound": false,
  "sub_intent_candidates": ["candidate_filter"],
  "sub_intent_evidence": [
    {{"intent": "candidate_filter", "evidence": ["谁会", "Python"], "reason": "问题要求按技能查找候选人。"}}
  ],
  "scenario_decisions": {{
    "candidate_filter": {{"scenario": "hard_filter", "confidence": 0.95, "evidence": ["谁会", "Python"], "reason": "用户提出明确技能准入条件。", "source": "llm"}}
  }},
  "conditions": [
    {{"type": "skill", "raw_value": "Python", "evidence": "Python", "reason": "用户要求会 Python。"}}
  ],
  "normalized_conditions": [],
  "context_policy": {{"uses_context": false, "context_ref_type": "none", "evidence": [], "reason": "当前问题没有明确上下文指代。"}},
  "requires_jd": false,
  "requires_evidence": false,
  "allowed_tool_names": [],
  "risk_flags": []
}}

用户问题:
{question}
"""


def build_plan_repair_prompt(
    *,
    question: str,
    router_output: RouterOutput,
    allowed_tools_by_intent: dict[str, list[str]],
    tool_specs: dict[str, Any],
    previous_plan: QueryPlan | None = None,
    validation_errors: list[str] | None = None,
) -> str:
    """构建计划修复提示词并返回。"""
    repair = ""
    if previous_plan is not None:
        repair = f"""
上一次 plan:
{previous_plan.model_dump_json(indent=2)}

validator errors:
{json.dumps(validation_errors or [], ensure_ascii=False, indent=2)}
"""
    return f"""你是简历问答系统的 QueryPlan repair node。只输出修复后的 QueryPlan，不回答用户问题，不调用工具，不写自然语言答案。

用户问题:
{question}

router 输出:
{router_output.model_dump_json(indent=2)}

每个 intent 允许的工具:
{json.dumps(allowed_tools_by_intent, ensure_ascii=False, indent=2)}

工具参数契约:
{json.dumps(tool_specs, ensure_ascii=False, indent=2)}

硬规则:
- tool_calls 只能使用对应 intent 允许的工具，参数名必须严格匹配工具参数契约。
- 不要输出工具没有声明的参数；例如 resolve_candidate_reference 只能使用 text 和可选 session_context，不能使用 names/candidate_names。
- 你只规划，不执行工具；不要提前查候选人、评分、排序或证据。
- 不要编造 resume_identity；除非用户直接给出完整 resume_identity，否则候选人 ID 必须来自 resolve_candidate_reference 的输出。
- 工具间依赖必须用 output_key 和 $变量路径，例如 "$resolved_candidates.candidate_ids"。
- 如果参数依赖前序工具结果，不要填空数组、空字符串或猜测值。
- count 问题：候选人来源工具 output_key="candidate_pool"，count_candidates(candidates="$candidate_pool.resume_identity[]")。
- 开放召回/软发现：命中 router open_recall_terms 的候选人发现问题使用 hybrid_search_candidates(query=<清理后的检索问题>)，它只做召回，不做硬性准入。
- 事实核查不要使用全局语义召回：例如“X 有没有 Y 经验/背景”必须 resolve_candidate_reference -> search_candidate_evidence，并把 evidence 绑定到 resolved candidate。
- 硬性筛选不要使用 query-only hybrid：例如“查询能源领域候选人 / 会 Python 和 SQL 的候选人有多少个”必须使用 filter_candidates(<normalized_value 条件>)；hybrid_search_candidates 只用于开放召回。
- 优先使用 router.normalized_conditions 生成工具参数；不要直接把 evidence 当工具参数。
- SQL/filter 参数使用 normalized_value：domain 默认进入 domains_any，出现“同时属于/兼具/都具备”时进入 domains_all；skill 进入 skills_all；concept 进入 concepts_all。证据查询 query 可以使用 retrieval_terms，例如 "推荐系统 金融风控 项目经验"。retrieval_terms 不能作为候选人准入条件。
- 在调用 hybrid_search_candidates/search_candidate_evidence/filter_candidates 前，基于 normalized_conditions 清理 query/参数：去掉“帮我/有哪些/候选人/刚才/上一次/介绍一下”等话术，只保留候选人姓名、领域、技能、项目、职责、经历等实体或条件。
- session_context 只传给 resolve_candidate_reference；其他工具参数不得从上轮上下文继承候选人，除非当前问题含有“他/她/这个人/刚才那个人/第一名/他们”等明确指代。
- candidate_compare_pair：resolve_candidate_reference(output_key="resolved_candidates") -> build_comparison_pack(candidate_ids="$resolved_candidates.candidate_ids", depends_on=["resolved_candidates"])。
- candidate_profile_intro：resolve_candidate_reference(output_key="resolved_candidate") -> get_candidate_profiles_intro(candidate_ids="$resolved_candidate.candidate_ids") -> search_candidate_evidence(query="", candidate_ids="$resolved_candidate.candidate_ids", scope="both")。画像只来自 SQLite，工作和项目证据必须通过显式 evidence tool result 提供。
- ranking：load_default_jd_criteria(output_key="criteria") -> score_candidates_for_jd(criteria="$criteria", output_key="scores") -> rank_candidates(scored_candidates="$scores")。
- evidence_question 必须包含证据查询工具。
- 联系方式默认隐藏，不要规划 include_contact=true，除非用户明确问联系方式。
- facts_must_come_from_tools：所有人名、数量、项目、年限、分数都只能来自工具结果。

{repair}
"""


def build_semantic_planner_prompt(
    *,
    question: str,
    router_output: RouterOutput,
    scenarios_by_intent: dict[str, str],
    tool_capabilities_by_intent: dict[str, list[dict[str, str]]],
    semantic_needs_by_intent: dict[str, dict[str, list[str]]],
) -> str:
    """构建语义planner提示词并返回。"""
    return f"""你是简历问答系统的 semantic planner。只输出 SemanticPlan，不回答用户问题，不调用工具，不写 executor 参数引用。

用户问题:
{question}

router 输出:
{router_output.model_dump_json(indent=2)}

Execution Policy 已确定的 scenario:
{json.dumps(scenarios_by_intent, ensure_ascii=False, indent=2)}

每个 intent 允许建议的工具能力:
{json.dumps(tool_capabilities_by_intent, ensure_ascii=False, indent=2)}

每个 intent 的 YAML 语义需求:
{json.dumps(semantic_needs_by_intent, ensure_ascii=False, indent=2)}

你的职责:
- 根据 router intent/sub_intent_candidates 为每个目标生成一个 semantic step。
- 每个 step 只说明 intent、scenario、needs、tool_hints、tool_hint_scores、conditions、requires_jd、requires_evidence、reason。
- intent/sub intents、conditions、context_policy 必须继承 router 输出，不要重新分类或改写。
- scenario 必须继承 Execution Policy，不要重新判断。
- YAML required needs 不能删除；只允许从对应 intent 的 optional needs 中追加语义需求。
- tool_hints 只能从对应 intent 允许的工具能力中选择。它们只是建议，Compiler 会再次裁决。
- tool_hint_scores 用于表达建议置信度和理由；source 只能填 "llm" 或省略，不得伪造 policy、template or compiler_required。
- 不要生成 ToolCallSpec、工具参数、output_key、depends_on、$ref、候选人 ID 或工具结果。
- normalized_conditions 必须来自 router.normalized_conditions；不要直接把用户 evidence 当 SQL 参数。
- 复合问题必须为每个 sub_intent_candidates 生成一个 step。
- 用户问“谁比较好/谁适合/推荐/排序”时，ranking step 需要 requires_jd=true。
- 用户问“项目体现在哪里/依据/证据/理由/原因/proof/evidence/reason”时，需要 requires_evidence=true。
- 用户问“X 有没有 Y 经验/背景”时，这是单人事实核查，不是开放召回；tool_hints 应指向 resolve_candidate_reference 和 search_candidate_evidence。
- 用户问“满足某个可结构化条件的候选人/有几个/都有谁”时，这是硬性筛选；tool_hints 应优先 filter_candidates，不要用 query-only hybrid_search_candidates。“能源领域候选人”只是这类问题的一个例子。
- domain 默认按 domains_any 并集筛选；只有“同时属于/兼具/都具备”才按 domains_all 交集筛选。skill 和 concept 默认分别按 skills_all、concepts_all 交集筛选；不同类型分组之间也取交集。
- 只有 scenario=open_recall 的开放发现问题才使用 hybrid_search_candidates；hard_filter 禁止使用 query-only hybrid_search_candidates。
- 不要创造不存在的事实、人名、数量、分数、项目。

例子:
- “有多少个金融领域候选人，都有谁？” -> steps: candidate_count needs=["filter","count"], candidate_list needs=["filter","list"]。
- “找找和金融风控相关、可能合适的候选人” -> candidate_filter scenario=open_recall，可追加 needs=["semantic_recall"]，tool_hints 建议 hybrid_search_candidates。
- “金融/运营/能源候选人有几个，谁最强，依据是什么？” -> steps: candidate_count + candidate_ranking + evidence_question；保留 count、ranking 和 evidence 三个语义目标。
- “这些人里谁适合金融岗位？” -> candidate_ranking，context_policy uses_context=true/context_ref_type=candidate_pool。
"""


def build_aggregator_prompt(
    *,
    question: str,
    plan: QueryPlan,
    compact_tool_results: list[dict[str, Any]],
    previous_answer: AggregatedAnswer | None = None,
    answer_errors: list[str] | None = None,
) -> str:
    """构建aggregator提示词并返回。"""
    repair = ""
    if previous_answer is not None:
        repair = f"""
上一次答案:
{previous_answer.model_dump_json(indent=2)}

answer validator errors:
{json.dumps(answer_errors or [], ensure_ascii=False, indent=2)}
"""
    return f"""你是简历问答系统的 aggregator。只基于 tool_results 写中文答案，并返回 AggregatedAnswer JSON。

用户问题:
{question}

plan:
{plan.model_dump_json(indent=2)}

tool_results 摘要:
{json.dumps(compact_tool_results, ensure_ascii=False, indent=2)}

通用硬规则:
- 不要新增 tool_results 里没有的人名、数量、项目、年限、分数、学校、公司、技能。
- 空结果是合法事实：候选人集合为空就回答 0 位；候选人已解析但 evidence 为空，就回答“目前没有查到对应经验/证据”，不要换成其他候选人或自由推断。
- 用户当前问题出现了明确候选人姓名/别名时，以当前问题和 tool_results 为准；不要把 session_context 中上一轮候选人的事实带入答案。
- count 必须来自 count_candidates。
- 排序必须说明基于 JD scoring；排序顺序必须来自 rank_candidates，不能重排。
- ranking 顺序只能来自 rank_candidates，不要按自己的判断调整名次。
- 联系方式默认隐藏，除非 tool_results 明确包含 contact 且用户明确要求。
- 不要输出年龄、性别、婚育、民族、政治面貌、照片等敏感属性。
- claims 中每个非 other claim 都必须把 supported_by 写成对应 tool_name。
- 使用证据的 claim 必须填写 evidence_ids；不要填写 tool_results 里不存在的 evidence_id。
- 如果返回 used_evidence_refs，必须为每条 evidence ref 填 summary，40-80 字，保留候选人、项目/经历、行为、技术/领域或职责。
- 每次回答正文都必须包含“主要依据：”。有 EvidenceRef 时使用 2-3 条 evidence summary；没有 EvidenceRef 时说明依据来自哪个结构化工具结果或 canonical artifact。
- 答案正文不要堆长证据原文；“主要依据：”只写总结，不额外复制长原文。

双人比较回答契约:
- 如果 intent=candidate_compare_pair，只能使用 build_comparison_pack，不能引入第三个候选人。
- 回答必须先给“结论”，再给“对比依据”。
- 对比答案的依据最多 2-3 条，用证据 summary 概括，不要复制长原文。
- 用户问“谁更好/谁更强”但没有 JD 时，不要说绝对更好；应给出有边界的建议，例如“在当前简历事实下，若按 X 维度更倾向 A；若岗位更看重 Y 则 B 也合适”。
- 必须分别说明两位候选人的优势和短板/不确定点，避免只说“各有优势”。
- 必须为两位候选人各生成一个 comparison claim：subject=<candidate_name>, value={{"recommended": true/false, "basis": "简短依据"}}。

结构化 claim 规则:
- count claim: claim_type=count, value=<count>。
- name/profile claim: subject=<candidate_name>。
- ranking claim: subject=<candidate_name>, value={{"rank": n, "score": x}}。
- comparison claim: subject=<candidate_name>, value={{"recommended": true/false}}，可以附加 basis。
- 输出必须符合 AggregatedAnswer schema。

{repair}
"""


def tool_specs_from_policy(tool_policy: dict[str, Any], tool_names: Iterable[str]) -> dict[str, Any]:
    """从策略提取工具规格集合并返回。"""
    tools = dict(tool_policy.get("tools", {}) or {})
    output: dict[str, Any] = {}
    for name in tool_names:
        meta = dict(tools.get(name, {}) or {})
        output[str(name)] = {
            "deterministic": bool(meta.get("deterministic", False)),
            "read_only": bool(meta.get("read_only", True)),
        }
    return output
