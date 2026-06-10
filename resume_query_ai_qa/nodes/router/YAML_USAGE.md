# Router YAML Usage

这份文档是 YAML 字段地图，不是 router 流程文档。

它只回答一个问题：

```text
读 router 时，哪些 YAML 字段真的和 router 有关？
```

`load_config()` 会一次性加载所有 runtime YAML，所以代码里到处都能拿到
`config.xxx`。但这不代表每个 YAML 都是 router 负责。判断边界要看：

```text
哪个函数读取了哪个字段
这个字段影响 RouterOutput 的哪个部分
后续 node 是否才是真正消费者
```

## 分类总览

| 分类 | YAML | Router 关系 |
|---|---|---|
| Router 直接使用 | `router_rules.yaml` | 规则词表、上下文、guard、risk flag |
| Router 直接使用 | `intents.yaml` | intent 合法集合、requires_* 默认值 |
| Router 直接使用 | `scenarios.yaml` | scenario 合法性、rule fallback scenario |
| Router 直接使用 | `tool_policy.yaml` | finalizer 计算单 intent 的 `allowed_tool_names` |
| Router 间接使用 | `condition_rules.yaml` | 通过 `extract_conditions()` 补 raw conditions |
| Router 间接使用 | `shared_taxonomy/` | 通过条件抽取识别 domain/skill/concept |
| 后续节点主责 | `compiler_templates.yaml` | execution policy / compiler 选择 workflow |
| 后续节点主责 | `evidence_policy.yaml` | executor / validator / answer grounding |
| 后续节点主责 | `validation.yaml` | validator / repair 重试和检查 |
| 后续节点主责 | `answer_layouts.yaml` | aggregator / renderer |
| 后续节点主责 | `aggregator_tasks.yaml` | aggregator |
| 后续节点主责 | `jd_scoring.yaml` | scoring tools / JD scoring |

## router_rules.yaml

这是 router 最核心的规则 YAML。

| 字段 | 主要读取位置 | 作用 | 影响字段 |
|---|---|---|---|
| `preprocess` | `conditions.preprocess_router_question` | 标点归一、去掉开头 filler terms | cleaned question |
| `out_of_scope` | `signals.is_resume_domain_question`、`guard.should_force_out_of_scope` | 判断是否不属于简历问答范围 | `intent=out_of_scope` |
| `signals` | `signals.py`、`rules.py`、`guard.py` | 发现 profile/project/evidence/open_recall 等文本信号 | draft intent、scenario fallback |
| `pair_compare` | `signals.looks_like_pair_compare`、`guard.apply_pair_compare_guard` | 判断两人对比 | `candidate_compare_pair` |
| `resume_domain` | `signals.is_resume_domain_question` | 判断是否是简历/候选人领域问题 | `out_of_scope` 或继续路由 |
| `intent_rules` | `rules.py`、`signals.py` | 规则 fallback 的 intent 触发词 | `sub_intent_candidates` |
| `compound_rules` | `guard.detect_compound_sub_intents`、`finalizer.finalize_requires_evidence` | 复合问题检测、证据需求判断 | `sub_intent_candidates`、`requires_evidence` |
| `context_ref_rules` | `context_resolver`、`signals.py`、`guard.py` | 解析“第一名/这些人/这两个人”等上下文引用 | `context_policy` |
| `context_references` | 旧兼容配置 | 历史/兼容形态，优先看 `context_ref_rules` | 不建议继续扩展 |
| `context_resolution` | `signals.py`、`guard.py` | 定义上下文 ref type 分类和当前轮引用规则 | `context_policy`、intent convergence |
| `intent_convergence` | `guard.apply_intent_convergence_guard` | 把 follow_up/单人适配类草稿收敛成具体 intent | `intent`、`sub_intent_candidates` |
| `candidate_scope_rules` | plan building / scope rules | 候选人作用域优先级，主要给后续计划构造用 | 后续 QueryPlan scope |
| `ranking_intent_rules` | `signals.py`、`guard.py` | 判断多人排序优先于两人比较 | `candidate_ranking` |
| `jd_selection_rules` | JD / planner 相关规则 | JD 来源和限制，主要给后续 scoring/planner 用 | 后续 JD criteria |
| `sensitive_interview_terms` | `signals.py`、`guard.apply_safety_guard` | 招聘敏感属性拦截 | `out_of_scope`、`risk_flags` |
| `intent_reasons` | `rules.intent_reason`、`finalizer.finalize_sub_intent_evidence` | 生成子 intent 解释 | `sub_intent_evidence.reason` |
| `risk_flags` | `finalizer.finalize_risk_flags` | risk flag 白名单 | `risk_flags` |

一句话：

```text
router_rules.yaml = router 的规则词表、硬规则、上下文和审计标记来源。
```

## intents.yaml

`intents.yaml` 定义“用户想做什么”。

| 字段 | 主要读取位置 | Router 中的作用 |
|---|---|---|
| `intents` 顶层 key | `llm.py` | 校验 LLM 输出的 intent 是否合法 |
| `description/examples` | router prompt | 给 LLM 路由提示 |
| `requires_jd_criteria` | `finalizer.finalize_requires_jd` | 权威重算 `requires_jd` |
| `requires_evidence` | `finalizer.finalize_requires_evidence` | 权威重算 `requires_evidence` |
| `semantic_needs` | config 查询方法 / planner compiler | 后续节点判断需要哪些语义材料 |
| `scenario_optional_needs` | config 查询方法 / planner compiler | 某 scenario 下额外需要什么，比如 `semantic_recall` |
| `fallback_when_no_jd` | scoring/planner 相关 | 缺 JD 时后续如何补默认 JD |
| `scenario_defaults` | config 查询方法 | scenario 级默认语义需求，当前 router finalizer 没直接用它重算 |

注意：

```text
semantic_needs / scenario_optional_needs 不是 RouterOutput 字段。
它们更多是 planner/compiler 读 RouterOutput 后继续决策时使用。
```

## scenarios.yaml

`scenarios.yaml` 定义“这件事该怎么执行”。

| 字段 | 主要读取位置 | 作用 |
|---|---|---|
| `scenarios.*.allowed_intents` | `config.allowed_scenarios_for_intent`、`finalizer.finalize_scenario_decisions` | 判断 draft scenario 对某 intent 是否合法 |
| `scenarios.*.planner` | `config.planner_for_scenarios` | 后续 execution policy 选择 rule planner 或 LLM planner |
| `scenarios.*.description/examples` | router prompt / 文档 | 帮 LLM 和人理解 scenario |
| `resolution_rules` | `rule_scenario_decisions` | LLM 缺失/非法 scenario 时的规则 fallback |

合法性判断例子：

```yaml
compare_rank:
  allowed_intents: [candidate_compare_pair, candidate_ranking, jd_scoring]
```

所以：

```text
candidate_ranking + compare_rank = 合法
candidate_ranking + hard_filter = 不合法，finalizer 会用 resolution_rules 修正
```

## condition_rules.yaml + shared_taxonomy

这组不是 router 独占。它们是公共条件抽取/归一化规则，`condition_normalizer`
和 plan building 也会继续使用。

Router 使用方式：

```text
complete_router_conditions
-> extract_conditions(question)
-> list[QueryCondition]
```

| 字段 | 主要读取位置 | Router 关系 |
|---|---|---|
| `extraction.major_pattern` | `extract_conditions` | 抽 `major` raw condition |
| `extraction.scopes` | `extract_conditions` | 抽 `scope` raw condition |
| `taxonomy_alias_exclusions` | `extract_conditions` | 避免 taxonomy 假阳性，比如“推荐谁”不是 concept=推荐 |
| `condition_types` | `cleaned_retrieval_query`、后续参数生成 | 主要给后续 condition/tool 参数使用 |
| `preferred_type_aliases` | `normalize_conditions` | condition_normalizer 阶段限定 taxonomy 匹配类型 |
| `preference_target` | `mark_preference_targets` | 标记“适合做什么”的目标条件，后续排序/评分使用 |
| `domain_filter` | `filter_arguments_from_conditions` | 多 domain 是 any 还是 all |
| `cleaning.major_prefixes` | `_clean_major_value` | 清理专业抽取结果 |
| `cleaning.dialog_scaffolding` | plan building query args | 后续检索 query 清理 |
| `cleaning.intent_scaffolding` | plan building query args | 后续检索 query 清理 |

历史说明：

```text
structured_project_tags 当前不再作为 router 依赖。
如果旧文档或历史 diff 里看到它，可以按历史遗留/已清理配置理解。
```

`shared_taxonomy/` 提供可匹配的知识词库：

```text
domain: 金融、计算机、能源...
skill/concept: Python、风控、推荐系统...
aliases/retrieval_terms: 别名和检索扩展词
```

重要边界：

```text
candidate_name 不走 shared_taxonomy。
候选人名字来自数据层，由 router 的 candidate_reference_conditions 生成。
```

## tool_policy.yaml

Router 只消费很小一部分：finalizer 给单 intent 计算 `allowed_tool_names`。

| 字段 | 主要读取位置 | Router 关系 |
|---|---|---|
| `intent_tools.*.allowed_tools` | `config.allowed_tools_for_intent` | 单 intent 的默认工具白名单 |
| `intent_tools.*.scenarios.*.allowed_tools` | `config.allowed_tools_for_intent(intent, scenario)` | scenario 级工具白名单 |
| `tools.*` metadata | planner/compiler/validator | 后续节点使用，不是 router 主责 |
| `preferred_tools/forbidden_tools/preferred_tool_hints` | planner/compiler | 后续节点使用 |

注意：

```text
compound 和 out_of_scope 的 allowed_tool_names 在 router finalizer 保持 []。
后续 compiler 会按每个 sub_intent 分别解析工具。
```

## RouterOutput 字段和 YAML 来源

| RouterOutput 字段 | 主要 YAML 来源 | 负责阶段 |
|---|---|---|
| `intent` | `router_rules.intent_rules`、`intents.yaml` | LLM/rule draft + guard |
| `is_compound` | `router_rules.compound_rules` | guard + finalizer shape |
| `sub_intent_candidates` | `router_rules.intent_rules`、`compound_rules` | rule draft + guard |
| `sub_intent_evidence` | `router_rules.intent_reasons` | rule draft + finalizer shape |
| `scenario_decisions` | `scenarios.yaml.allowed_intents`、`resolution_rules` | LLM/rule draft + finalizer contract |
| `conditions` | `condition_rules.yaml`、`shared_taxonomy/`、candidate mentions | rule draft + condition completion |
| `normalized_conditions` | 无，router 阶段保持空 | condition_normalizer node 负责 |
| `context_policy` | `router_rules.context_ref_rules`、`context_resolution` | signals + guard |
| `requires_jd` | `intents.yaml.requires_jd_criteria` | finalizer derived flags |
| `requires_evidence` | `intents.yaml.requires_evidence`、`router_rules.compound_rules.evidence_terms` | finalizer derived flags |
| `allowed_tool_names` | `tool_policy.yaml.intent_tools` | finalizer contract |
| `risk_flags` | `router_rules.risk_flags.allowed_prefixes` | guard/conditions + finalizer cleanup |

## 怎么读 YAML 才不乱

建议按这个顺序读：

```text
1. router_rules.yaml
   先看 router 自己的词表、guard、上下文、risk_flags。

2. intents.yaml
   看有哪些 intent，以及每个 intent 是否 requires_jd / requires_evidence。

3. scenarios.yaml
   看每个 intent 可以走哪些 scenario，以及 rule fallback 怎么选 scenario。

4. condition_rules.yaml + shared_taxonomy/
   看 conditions 是怎么抽出来的，但记住它不是 router 独占。

5. tool_policy.yaml
   只在 finalizer 的 allowed_tool_names 和后续 compiler 里看。
```

如果某个 YAML 字段只影响 planner/compiler/validator，就不要把它当成 router 主链路的一部分。
