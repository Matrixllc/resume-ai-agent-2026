# Field Flow Reference

这份文档只回答一个问题：用户问题进入 graph 后，关键字段是谁产生的、谁消费的、对上下游有什么影响。

核心原则：

> intent 表示“用户想要什么”，scenario 表示“应该用什么执行约束去做”，ExecutionDecision 表示“这次走 template 还是 generic”。

## 一页链路

```text
question
-> RouterOutput
-> normalized RouterOutput
-> ExecutionDecision
   -> template: SemanticPlan(from router) -> QueryPlan
   -> generic: SemanticPlan(planner) -> QueryPlan
-> ToolCallSpec / ArtifactBinding
-> ToolResult
-> AggregatedAnswer
```

## `RouterOutput.intent`

产生节点：`router`

消费节点：

- `execution_policy`：读取 router/finalizer 已确定的 scenario，并决定 compiler 路径。
- `planner`：generic 路径下按 intent 生成 `SemanticPlan.steps`。
- `plan_compiler`：按 intent 选择 workflow template 或 generic tools。
- `validators`：检查这个 intent 是否用了合法工具、是否满足 evidence/JD/context 要求。
- `aggregator`：选择回答方式和 layout。

意义：

`intent` 是用户主目标，比如 `candidate_profile_intro`、`candidate_filter`、`candidate_ranking`。它不等于工具名，也不等于执行路径。router 不应该因为 intent 是 `candidate_filter` 就直接决定调用 `filter_candidates`，工具绑定属于 compiler。

## RouterOutput 字段生命周期

router 内部现在按固定流程收口字段：

```text
query_preprocess
-> llm_or_rule_classify
-> payload_normalize
-> schema_validate
-> rule_guard
-> condition_completion
-> finalizer
```

| 字段 | 初值来源 | 权威来源 | 说明 |
|---|---|---|---|
| `intent` | LLM 或 rule fallback | schema validate + rule guard + finalizer | 表示用户主目标；高风险误判会被 rule guard 覆盖 |
| `sub_intent_candidates` | LLM 或 rule fallback | compound guard + finalizer | compound 问题必须显式拆出 count/list/rank/evidence 等子目标 |
| `scenario_decisions` | LLM 或 rule fallback | schema validate + rule guard + finalizer | 每个 intent 的执行语义；LLM 合法输出会被保留，缺失/非法时回到 rule fallback |
| `conditions` | LLM 或 rule fallback | condition_completion | 只保留原始条件，如 domain/skill/concept/candidate_name/scope |
| `normalized_conditions` | router 保持空 | `condition_normalizer` | router 不做标准化，避免和 normalizer 职责重叠 |
| `context_policy` | LLM 或 rule fallback | rule guard | “他/这些人/第一名/这个岗位”等上下文指代由 guard 补齐 |
| `requires_jd` | LLM 初步判断 | finalizer | ranking/scoring 或 intent 默认值触发；不信任 LLM 最终值 |
| `requires_evidence` | LLM 初步判断 | finalizer | profile/evidence/compare/ranking/interview 或证据词触发 |
| `allowed_tool_names` | LLM 默认 `[]` | finalizer 从 `tool_policy.yaml` 填 | debug/约束提示，不代表 router 选工具 |
| `risk_flags` | fallback/guard 追加 | finalizer 白名单清理 | 生产审计字段，说明 LLM fallback、规则覆盖、条件补全等 |

典型例子：

```text
Python 是什么？
-> rule_guard 强制 out_of_scope
-> allowed_tool_names=[]
```

```text
谁会 Python？
-> intent=candidate_filter
-> condition_completion 补 conditions=[skill: Python]
-> condition_normalizer 后续生成 normalized_conditions=[skill: Python]
```

```text
金融候选人有几个，谁最强，依据是什么？
-> compound_guard 补 candidate_count + candidate_ranking + evidence_question
-> finalizer 重算 requires_jd=true, requires_evidence=true
```

## `sub_intent_candidates`

产生节点：`router`

消费节点：

- `execution_policy`：compound 时读取每个子 intent 对应的 scenario。
- `plan_compiler`：把 compound 编译为多个 `SubTaskPlan`。
- `validator`：检查 compound plan 是否漏掉子任务。
- `aggregator`：按多个子任务组织答案。

典型例子：

`有多少个金融领域候选人，都有谁？`

```text
intent=compound
sub_intent_candidates=[candidate_count, candidate_list]
```

这个字段的价值是让“一个问题多个目标”显式化。后续 count 和 list 会被 compiler 绑定到同一个 candidate source，避免数量和名单不一致。

## `normalized_conditions`

产生节点：`condition_normalizer`

消费节点：

- `execution_policy`：判断是否有硬筛选 scope。
- `planner`：作为 semantic step 条件。
- `plan_compiler`：生成 tool arguments，比如 `domains_any=["Finance"]`。
- `plan_validator`：检查条件是否真的进入工具参数。
- `executor/tools`：最终按参数查 SQL/Chroma。

典型例子：

```text
问题：谁会 Python？
normalized_conditions:
  - type=skill
    normalized_value=Python
```

它解决的是自然语言不稳定的问题。用户可以说“金融背景”“金融领域”“finance”，下游不能每个节点都各自猜一遍，必须先规范化。

## `context_policy`

产生节点：`router`。`condition_normalizer` 只透传并记录这个字段，不重新解释上下文。

消费节点：

- `plan_compiler`：决定是否把 `last_candidate_id`、`last_candidate_pool_ids`、`last_ranking_candidate_ids` 绑定进 tool args。
- `plan_validator`：如果缺上下文，触发 fail；只有双人比较缺少明确两位候选人时才 clarification。
- `executor`：通过 session context 解析实际 candidate ids。
- `final`：更新下一轮可用的 session context。

典型上下文：

| 表达 | `context_ref_type` | 需要的 session 字段 |
|---|---|---|
| `这些人` | `candidate_pool` | `last_candidate_pool_ids` |
| `他` | `last_candidate` | `last_candidate_id` |
| `第一名` | `ranking_top` | `last_ranking_candidate_ids` |
| `这两个人` | `comparison_pair` | `last_comparison_candidate_ids` |

如果用户问 `他有哪些金融经历？` 但 session 里没有 `last_candidate_id`，plan validator 会报 `missing required last_candidate context`，graph 进入 fail，而不是让 LLM 猜一个人或追问补上下文。

## `scenario`

产生节点：`router/finalizer`

产生规则：

- LLM router 优先按 prompt 中的 `scenarios.yaml` 规范输出 `scenario_decisions`。
- `nodes.router.llm.validate_router_payload_schema()` 校验每个 intent 是否都有合法 scenario；缺失或非法时整包回到 rule fallback。
- `nodes.router.finalizer.finalize_scenario_decisions()` 保留合法 LLM scenario，并对缺失、非法或 guard 改动后的场景调用 `core.rules.execution_policy_rules.rule_scenario_decisions()` 补齐。

消费节点：

- `execution_policy`：只读取 `RouterOutput.scenario_decisions`，不重新解释问题。
- `core.rules.execution_policy_rules.match_workflow()`：workflow template 会声明支持哪些 scenario。
- `planner`：generic path 下写入 `SemanticStep.scenario`。
- `plan_compiler`：generic binding 时按 scenario 读取 allowed/preferred/forbidden tools。
- `plan_validator`：按 scenario 检查工具是否合法。

`scenario` 不是业务场景名，而是执行约束协议。同一个 intent 在不同问法下可能走不同 scenario。

核心关系：

```text
intent = 用户任务目标
scenario = 本次执行约束
```

LLM 可以先判断 scenario，但不能越过合同。只有通过 schema、YAML
allowed intent/scenario 校验和 rule guard 的 LLM scenario 才会被保留；
rule scenario resolver 是 LLM 不可用、LLM 合同不合法或 guard 改写后的 fallback。

| Scenario | 含义 | 典型问题 | 常见路径 |
|---|---|---|---|
| `soft_summary` | 候选人画像展示 | `介绍一下孟连星` | 通常 template，跳过 planner |
| `hard_filter` | 结构化硬筛选 | `谁会 Python？` | template 或 rule generic |
| `open_recall` | 语义开放召回 | `谁有金融背景？` | generic + evidence/search |
| `fact_check` | 单候选证据核查 | `孟连星有哪些金融经验？` | template 或 evidence workflow |
| `evidence_lookup` | 候选人不明确的证据召回 | `谁做过风控相关项目？` | generic |
| `compare_rank` | 排序/比较/评分 | `这些人里谁适合金融岗位？` | template workflow |
| `out_of_scope` | 非简历问题 | `今天天气怎么样？` | no tools |

### Intent -> Scenario

| Intent | 可能 Scenario | 判定依据 |
|---|---|---|
| `candidate_profile_intro` | `soft_summary` | 画像、介绍、个人信息展示 |
| `candidate_count` | `hard_filter` / `open_recall` | 默认 hard；问法像开放召回时 open |
| `candidate_list` | `hard_filter` / `open_recall` | 默认 hard；问法像开放召回时 open |
| `candidate_filter` | `hard_filter` / `open_recall` | 有结构化 scope 时 hard；开放召回词或 requires_evidence 时 open |
| `evidence_question` | `fact_check` / `evidence_lookup` | 有候选人或上下文时 fact_check；否则 evidence_lookup |
| `candidate_compare_pair` | `compare_rank` | 双人比较 |
| `candidate_ranking` | `compare_rank` | 多人排序、岗位匹配 |
| `jd_scoring` | `compare_rank` | JD 打分 |
| `out_of_scope` | `out_of_scope` | 非简历问题 |

### Scenario -> Intent

| Scenario | 通常服务的 Intent | 主要作用 |
|---|---|---|
| `soft_summary` | `candidate_profile_intro` | 命中画像 template，跳过 planner |
| `hard_filter` | `candidate_count`、`candidate_list`、`candidate_filter` | 结构化硬筛，禁用开放乱召回 |
| `open_recall` | `candidate_count`、`candidate_list`、`candidate_filter` | 开放召回，generic planner 可能用 LLM |
| `fact_check` | `evidence_question` | 候选人内证据核查 |
| `evidence_lookup` | `evidence_question` | 候选人不明确时的证据召回 |
| `compare_rank` | `candidate_compare_pair`、`candidate_ranking`、`jd_scoring` | 比较、评分、排序 |
| `out_of_scope` | `out_of_scope` | 不查简历 tools |

### 判定规则伪代码

这段对应 rule fallback 的 `core.rules.execution_policy_rules.resolve_scenario()`。
它不是正常 LLM 路径的唯一来源，而是 LLM 失败、漏字段、非法 scenario 或
guard 改写后用来补齐 `scenario_decisions` 的确定性算法：

```text
if intent == out_of_scope:
  scenario = out_of_scope

elif intent in [candidate_count, candidate_list]:
  if question 或 sub_intent_evidence 像开放召回:
    scenario = open_recall
  else:
    scenario = hard_filter

elif intent == candidate_filter:
  if question 或 sub_intent_evidence 像开放召回:
    scenario = open_recall
  elif normalized_conditions 里有 domain/skill/concept/keyword/major/job_intent/candidate_name:
    scenario = hard_filter
  elif requires_evidence:
    scenario = open_recall
  else:
    scenario = hard_filter

elif intent == evidence_question:
  if normalized_conditions 里有 candidate_name 或 context_policy.uses_context=true:
    scenario = fact_check
  else:
    scenario = evidence_lookup

elif intent in [candidate_compare_pair, candidate_ranking, jd_scoring]:
  scenario = compare_rank

elif intent == candidate_profile_intro:
  scenario = soft_summary
```

`_has_filter_scope()` 看的是 `normalized_conditions`，只要有明确的 `domain`、`skill`、`concept`、`keyword`、`major`、`job_intent` 或 `candidate_name`，就认为这个问题可以硬筛。

`_looks_like_open_recall()` 看 question 原文和 router 的 sub intent evidence，命中下面这些词就倾向 `open_recall`：

```text
可能、相关、类似、接近、找找、看看、这类、语义
semantic、similar、related、might、maybe
```

`_has_candidate_reference()` 看是否有候选人引用：`candidate_name` 或 `context_policy.uses_context=true`。有候选人引用的 `evidence_question` 是 `fact_check`，没有候选人引用的是 `evidence_lookup`。

### 同一个 Intent 的不同 Scenario

`candidate_filter + hard_filter`：

```text
问题：谁会 Python？
normalized_conditions=[skill: Python]
scenario=hard_filter
影响：倾向 filter_candidates；validator 要求 Python 被工具参数消费。
```

`candidate_filter + open_recall`：

```text
问题：找找可能有金融背景的人
question 命中“可能/找找”
scenario=open_recall
影响：generic planner 可能用 LLM；compiler 可接受 hybrid_search_candidates。
```

`evidence_question + fact_check`：

```text
问题：孟连星有哪些金融经验？
normalized_conditions=[candidate_name: 孟连星, domain: Finance]
scenario=fact_check
影响：通常 resolve_candidate_reference -> search_candidate_evidence。
```

`evidence_question + evidence_lookup`：

```text
问题：谁做过风控相关项目？
没有明确候选人
scenario=evidence_lookup
影响：更像开放证据召回，generic planner 可能参与。
```

关于 `soft_summary`：

你前面提到的 `softmax`，在当前代码里对应的是 `soft_summary`。它表示“画像展示类问题”，不是模型里的 softmax。比如 `介绍一下孟连星`：

```text
intent=candidate_profile_intro
scenario=soft_summary
ExecutionDecision.compiler=workflow_template
workflow_name=candidate_profile_intro
planner=rule
```

这条路通常跳过 LLM planner，由 template 直接编译出工具调用：先解析候选人，再取候选人画像。

## `ExecutionDecision`

产生节点：`execution_policy`

消费节点：

- `nodes.execution_policy.route_after_execution_policy()`：决定下一跳是 `plan_compiler` 还是 `planner`。
- `plan_compiler`：hybrid 模式下尊重 decision，不重新做业务分流。
- `trace` / API debug：解释为什么走 template 或 generic。

字段含义：

| 字段 | 意义 |
|---|---|
| `compiler` | `workflow_template` 或 `generic_tool_binding` |
| `planner` | generic path 是否用 `llm`，template path 通常是 `rule` |
| `workflow_name` | 命中的稳定 workflow |
| `scenarios` | 每个 intent 对应的执行约束 |
| `reason` | 可读决策原因 |

`ExecutionDecision.scenarios` 是从 `RouterOutput.scenario_decisions` 透传出来的
调度输入。它解释本轮为什么能命中某个 workflow 或为什么要进入 generic planner，
但不代表 `execution_policy` 重新计算了 scenario。

两条路：

```text
compiler=workflow_template
-> runner 跳过 planner
-> plan_compiler 按 compiler_templates.yaml 编译 QueryPlan

compiler=generic_tool_binding
-> runner 进入 planner
-> planner 产 SemanticPlan
-> plan_compiler 按 tool_policy.yaml 绑定合法 tools
```

## `SemanticPlan`

产生节点：`planner`，或 template path 下由 `semantic_plan_from_router()` 从 router 结果确定性生成。

消费节点：`plan_compiler`

意义：

`SemanticPlan` 是中间表达，只描述“想做什么”和“可能需要哪些工具线索”。它不是 executor 的输入，也不能直接调工具。

典型结构：

```text
SemanticPlan
  intent=candidate_filter
  steps:
    - intent=candidate_filter
      scenario=open_recall
      conditions=[Finance]
      tool_hints=[hybrid_search_candidates, search_candidate_evidence]
```

LLM planner 可以给 tool hints，但 hints 只是建议。generic compiler 仍然会用 `tool_policy.yaml`、source contract、artifact binding 决定哪些工具合法。

## `QueryPlan`

产生节点：`plan_compiler`

消费节点：

- `plan_validator`：先检查。
- `executor`：唯一可执行输入。
- `aggregator`：根据 intent/tool results 组织答案。
- `answer_validator`：按 plan 检查答案 claim。

意义：

`QueryPlan` 是可执行计划，包含真实工具调用、参数、依赖和产物绑定。

```text
QueryPlan
  tool_calls:
    - filter_candidates(output_key=candidate_pool)
    - count_candidates(depends_on=[candidate_pool])
```

## `ToolCallSpec.depends_on`

产生节点：`plan_compiler`

消费节点：`executor`、`plan_validator`

意义：

它告诉 executor 工具执行顺序和参数引用关系。比如 `count_candidates` 依赖 `candidate_pool`，就不能在 `filter_candidates` 之前执行。

## `ArtifactBinding`

产生节点：`plan_compiler`

消费节点：

- `plan_validator`：检查 source scope 是否冲突。
- `aggregator`：理解 count/list/rank/evidence 是否同源。
- debug trace：解释 rejected producers。

意义：

它是防错字段。比如 compound 问题：

```text
有多少个金融领域候选人，都有谁？
```

必须保证：

```text
filter_candidates(domain=Finance) -> candidate_pool
count_candidates(candidate_pool)
list answer also uses candidate_pool
```

如果 generic planner 暗示 `list_all_candidates`，compiler 会把它作为 rejected producer 记录下来，避免“人数是金融候选人，名单是全库”的错配。

## `ToolResult`

产生节点：`executor`

消费节点：

- `execution_validator`：检查工具是否失败、结果是否为空、证据是否足够。
- `aggregator`：答案事实来源。
- `answer_validator`：验证 count/name/ranking/evidence claim。

注意：工具结果是事实层。aggregator 可以把它表达成中文，但不能改变数量、名字、排名或证据。

## `decision_log`

产生节点：所有 graph node 都会通过 `_log_decision()` 记录。

消费位置：

- API debug summary。
- 前端 Debug 面板。
- 后端 `resume_query_ai_qa/logs/*.json`。

它是部署后排查问题的主线。看一条 bad case 时，先看 `decision_log` 的 node 顺序，再看 `fallback_reason`、`repair_action`、`validation_errors`。
