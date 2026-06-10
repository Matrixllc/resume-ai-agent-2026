# Project Walkthrough

这份文档用“问题如何变成答案”的方式讲 `ai-query`。它适合你读链路、给别人讲架构、追问每个 node 为什么这么设计。

核心判断：

> 这不是自由 Agent，而是一个有状态、有边界、有审计能力的问答编排框架。LLM 负责理解和表达，事实来自 tools，边界由 validators 和 trace 保障。

## 一页总览

```text
router
-> condition_normalizer
-> execution_policy
   -> template: plan_compiler
   -> generic: planner -> plan_compiler
-> plan_validator
-> executor
-> execution_validator
-> aggregator
-> answer_validator
-> final
```

框架视角：

| 阶段 | 对应 node | 作用 |
|---|---|---|
| Parse | `router` | 判断用户想干什么 |
| Normalize | `condition_normalizer` | 把自然语言条件规范化 |
| Route | `execution_policy` | 决定 template/generic |
| Plan | `planner` | generic 路径生成 SemanticPlan |
| Compile | `plan_compiler` | 生成 QueryPlan |
| Validate | `plan_validator` | 检查工具、scope、context |
| Execute | `executor` | 调用只读 tools |
| Validate Result | `execution_validator` | 检查工具结果是否足够 |
| Render | `aggregator` | 组织答案 |
| Validate Output | `answer_validator` | 防止最终答案编造 |

## Router 先做什么

router 是入口协议层，不是 planner。它内部先用 LLM 或 rule fallback 产出 draft，再经过确定性后处理：

```text
query_preprocess
-> llm_or_rule_classify
-> payload_normalize
-> schema_validate
-> rule_guard
-> condition_completion
-> finalizer
```

这几个动作的分工：

- `rule_guard`：强制处理 `Python 是什么？`、双人比较、compound、上下文指代、敏感面试问题。
- `condition_completion`：补漏 `domain/skill/concept/candidate_name/scope`，例如 `谁会 Python？` 补出 `skill=Python`。
- `finalizer`：保留合法 LLM `scenario_decisions`，用 rule fallback 补齐缺失或被 guard 改动后的场景，并重算 `requires_jd/requires_evidence/allowed_tool_names/risk_flags`。

router 会产出 `scenario_decisions`。LLM router 优先给每个 intent 判断 scenario；
如果 LLM 不可用、JSON 不合法、漏掉 scenario，或 scenario 不符合 `scenarios.yaml`
允许关系，schema validate 会整包回到 rule fallback。`execution_policy` 不重新解释
用户问题，只读取 router/finalizer 收口后的 scenario 来决定 template/generic。

## Template / Generic 怎么理解

template 是稳定快路径：

```text
router -> normalizer -> execution_policy -> plan_compiler
```

generic 是泛化路径：

```text
router -> normalizer -> execution_policy -> planner -> plan_compiler
```

区别不是“有没有 LLM 回答”，而是“要不要 LLM planner 参与规划”。

- template：工具顺序稳定，直接按 YAML workflow 编译。
- generic：语义更开放，先产 `SemanticPlan`，再按 tool policy 编译。
- aggregator 阶段仍可能用 LLM polish，但答案事实必须来自 tools。

## 读链路的固定顺序

每个问题都按这个顺序看：

```text
1. intent：用户要什么？
2. scenario：这个 intent 本次怎么执行？
3. ExecutionDecision：走 workflow_template 还是 generic_tool_binding？
4. QueryPlan：最终有哪些 tools、参数和 depends_on？
5. Validator：有没有 scope/context/evidence 错误？
```

这样读可以避免把 intent 和 scenario 混在一起。比如 `candidate_filter` 只是“找候选人”，但它可以是 `hard_filter`，也可以是 `open_recall`；真正决定工具约束的是 scenario。

## Case 1：`介绍一下孟连星`

这是单候选人画像，高频稳定。

```text
router:
  intent=candidate_profile_intro
  conditions=[candidate_name: 孟连星]

condition_normalizer:
  normalized_conditions=[candidate_name: 孟连星]

execution_policy:
  scenario=soft_summary
  compiler=workflow_template
  workflow_name=candidate_profile_intro

planner:
  跳过

plan_compiler:
  resolve_candidate_reference -> get_candidate_profiles_intro

executor:
  解析候选人 id
  读取候选人画像素材

aggregator:
  按画像 layout 组织答案

answer_validator:
  检查姓名、画像事实、联系方式隐藏策略
```

为什么这样做：

`soft_summary` 表示“画像展示”，不是模型里的 softmax。画像问题工具顺序稳定，走 template 比每次让 planner 重新规划更快、更稳定、更便宜。

## Case 2：`谁有金融背景？`

这是开放召回和硬筛选之间的典型问题，具体路径取决于 router/normalizer 判断。

可能路径 A：硬条件明确。

```text
intent=candidate_filter
normalized_conditions=[domain: Finance]
scenario=hard_filter
compiler=workflow_template 或 rule generic
tool=filter_candidates(domains_any=["Finance"])
```

scenario 影响：

```text
hard_filter
-> generic planner 即使参与，也倾向 rule
-> tool_policy 禁止 hybrid_search_candidates
-> validator 检查 Finance 是否进入 filter_candidates
```

可能路径 B：表达更开放，例如“找找可能有金融背景的人”。

```text
intent=candidate_filter
scenario=open_recall
compiler=generic_tool_binding
planner=llm 或 rule fallback
SemanticPlan: 召回金融相关候选人
generic compiler: 按 tool_policy 绑定 hybrid_search_candidates / search_candidate_evidence
```

scenario 影响：

```text
open_recall
-> generic planner 更可能用 LLM
-> compiler 允许 hybrid_search_candidates
-> answer 更强调召回依据，而不是硬条件命中
```

关键点：

- LLM planner 只生成 `SemanticPlan`，不能直接调工具。
- generic compiler 会拒绝不合法 tool hints。
- tools 返回结构化候选人或证据。
- aggregator 不能因为“看起来像金融”就自己补结论。

### 补充：`谁会 Python？`

这是 `candidate_filter + hard_filter` 的更干净例子。

```text
intent=candidate_filter
normalized_conditions=[skill: Python]
scenario=hard_filter
ExecutionDecision:
  如果命中稳定 workflow，就走 template
  否则 generic 里也优先 rule planner
compiler:
  只能把 Python 绑定到结构化 filter/search 合法参数
validator:
  检查 Python 是否被 plan 消费
```

核心区别：

`谁会 Python？` 是明确技能条件，不需要开放召回；`找找可能有金融背景的人` 是探索式表达，才需要 `open_recall`。

## Case 3：`有多少个金融领域候选人，都有谁？`

这是 compound：数量 + 名单。

```text
router:
  intent=compound
  sub_intent_candidates=[candidate_count, candidate_list]

normalizer:
  normalized_conditions=[domain: Finance]

execution_policy:
  scenarios:
    candidate_count=hard_filter
    candidate_list=hard_filter

plan_compiler:
  filter_candidates(domain=Finance) -> candidate_pool
  count_candidates(candidate_pool) -> candidate_count
```

关键点：

`ArtifactBinding` 会把 count/list 绑定到同一个 `candidate_pool`。如果某个 generic hint 想用 `list_all_candidates`，compiler 应该拒绝它，避免“人数来自金融筛选，名单来自全库”。

## Case 4：`这些人里谁适合金融岗位？`

这是候选池内排序。

```text
router:
  intent=candidate_ranking
  context_policy.uses_context=true
  context_ref_type=candidate_pool

session_context:
  last_candidate_pool_ids=[...]

plan_compiler:
  filter_candidates(candidate_ids=last_candidate_pool_ids, domain=Finance)
  load_default_jd_criteria 或 extract_jd_criteria
  score_candidates_for_jd
  rank_candidates

validator:
  检查 candidate_ids 是否被应用
```

关键点：

“这些人”是强 scope。系统不能偷偷全库排序。`plan_validator` 会检查 candidate_pool context 是否进入 plan。

## Case 5：`他有哪些金融经历？`

这是上下文指代 + 单候选证据核查。

有上下文：

```text
session_context.last_candidate_id=xxx
router.context_policy=last_candidate
scenario=fact_check
compiler/tool:
  resolve_candidate_reference("他")
  search_candidate_evidence(candidate_id=xxx, query=金融经历)
```

无上下文：

```text
router.context_policy=last_candidate
plan_validator:
  semantic: missing required last_candidate context
graph:
  fail
```

关键点：

系统不会猜“他”是谁。缺上下文不是 LLM 发挥空间，也不追问补齐，直接 fail。

### 补充：`孟连星有哪些金融经验？`

这是 `evidence_question + fact_check`。

```text
intent=evidence_question
normalized_conditions=[candidate_name: 孟连星, domain: Finance]
scenario=fact_check
ExecutionDecision:
  通常命中 evidence_question workflow
plan_compiler:
  resolve_candidate_reference
  search_candidate_evidence(query=金融经验, candidate_ids=孟连星)
validator:
  检查有候选人引用，且 evidence-required intent 有证据工具
```

scenario 影响：

`fact_check` 把问题限定在“明确候选人内核查证据”，不同于 `evidence_lookup` 的全局找证据。

## Case 6：`金融候选人有几个，谁最强，依据是什么？`

这是复杂 compound workflow。

```text
router:
  intent=compound
  sub_intent_candidates=[candidate_count, candidate_ranking, evidence_question]

execution_policy:
  workflow_name=scoped_count_rank_evidence

plan_compiler:
  filter_candidates(domain=Finance) -> candidate_pool
  count_candidates(candidate_pool)
  load_default_jd_criteria
  score_candidates_for_jd(candidate_pool)
  rank_candidates(scores)
  search_candidate_evidence(top ranked candidates)
```

为什么不是先全量查证据：

先 count/rank，再查 top evidence，速度更快，答案更聚焦，也更容易保证证据和排名同源。

## Case 7：`孟连星和孔德程谁更好？`

这是双人比较。

```text
router:
  intent=candidate_compare_pair
  conditions=[孟连星, 孔德程]
  scenario=compare_rank

plan_compiler:
  resolve_candidate_reference
  build_comparison_pack

validator:
  检查必须正好两个人

aggregator:
  基于 comparison_pack 组织比较，不凭空选赢家
```

如果解析出超过两个人，validator 会根据配置拒绝或转 ranking，避免 compare 和 ranking 边界混乱。

## Case 8：`针对孟连星信息，进行提问`

这是面试题生成。

```text
router:
  intent=interview_question_generation

compiler/tools:
  resolve_candidate_reference
  get_candidate_profile_intro / search_candidate_evidence

aggregator:
  基于候选人事实生成面试题
```

边界：

面试题可以围绕已有经历追问，但不能凭空创造候选人没有的项目或技能。

## Case 9：`今天天气怎么样？`

这是越界问题。

```text
router:
  intent=out_of_scope

execution_policy:
  scenario=out_of_scope

compiler:
  empty plan

executor:
  no tools

aggregator:
  返回边界说明
```

关键点：

不查简历工具是效率，也是安全边界。非简历问题不应该消耗检索资源，也不应该泄露候选人信息。

## Bad Case 怎么流转

| 异常 | 发现节点 | 处理 |
|---|---|---|
| 缺上下文 | `plan_validator` | fail |
| 双人比较缺少明确两位候选人 | `plan_validator` / `execution_validator` | clarification |
| 工具不合法 | `plan_validator` | plan_repair |
| 工具执行失败 | `executor` / `execution_validator` | execution_repair 或 fail |
| 证据不足 | `execution_validator` | evidence fallback 或 grounded empty answer |
| LLM 失败 | 当前 LLM node | rule fallback |
| 答案编造 | `answer_validator` | answer_rewrite 或 rule fallback |
| 非简历问题 | `router` | out_of_scope，不查 tools |

## 怎么讲这个架构

如果别人问“为什么不直接 Agent 调工具”，可以这样回答：

招聘问答对事实一致性要求高。自由 Agent 容易绕过工具、扩大 scope、编造证据。这里把链路拆成 router、planner、compiler、validator、executor、aggregator，是为了让每一步都有 contract、能 fallback、能 trace、能给运营配置。

最大的取舍：

> 牺牲一点自由 Agent 的灵活性，换来可解释、可验证、可部署、可运营。
