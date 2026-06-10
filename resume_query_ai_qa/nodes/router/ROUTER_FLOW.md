# Router Flow

Router 的职责只有一个：把用户问题收敛成 `RouterOutput`。

它不查 SQLite/Chroma，不生成工具计划，不回答用户问题。工具计划从后续
`condition_normalizer -> execution_policy -> planner/plan_compiler` 开始。

## 代码阅读顺序

```text
1. ROUTER_FLOW.md
2. node.py
3. llm.py
4. rules.py
5. signals.py
6. guard.py
7. conditions.py
8. finalizer.py
9. rule_types.py
```

## 5 阶段 Pipeline

```text
preprocess_router_question
-> build_router_draft
-> apply_router_guards
-> complete_router_conditions
-> finalize_router_output
```

| 阶段 | 文件 | 输入 | 输出 | 读 YAML | 改哪些字段 |
|---|---|---|---|---|---|
| preprocess | `conditions.py` | raw question | cleaned question | `router_rules.preprocess` | 不改 RouterOutput |
| draft | `llm.py` 或 `rules.py` | cleaned question + config | RouterOutput draft | `intents`、`scenarios`、`router_rules`、`condition_rules`、taxonomy | `intent`、`sub_intents`、`conditions`、`scenario_decisions`、`context_policy` 等草稿字段 |
| guards | `guard.py` | draft | guarded draft | `router_rules` | 可覆盖 `intent`、`sub_intents`、`context_policy`、`requires_*`、`risk_flags` |
| condition completion | `conditions.py` | guarded draft | completed draft | `condition_rules`、taxonomy、candidate mentions | 补 `conditions`，保持 `normalized_conditions=[]` |
| finalizer | `finalizer.py` | completed draft | final RouterOutput | `intents`、`scenarios`、`tool_policy`、`router_rules.risk_flags` | 权威重算派生字段 |

## 每个 py 文件职责

| 文件 | 职责 | 不负责 |
|---|---|---|
| `node.py` | 总流程编排，选择 LLM/rule draft | 业务规则、工具计划 |
| `llm.py` | LLM 生成完整 RouterOutput draft，修 payload，校验 schema/scenario | guard、condition completion、finalizer |
| `rules.py` | deterministic rule fallback draft | LLM、guard、权威字段收口 |
| `signals.py` | 文本信号检测，产 `RouterSignals` | 最终 intent 判断 |
| `guard.py` | 硬规则纠偏 draft | 生成原始 draft、最终收口 |
| `conditions.py` | query 清理、补 raw `QueryCondition` | `NormalizedCondition`、工具参数 |
| `finalizer.py` | RouterOutput 权威字段重算 | 重新理解自然语言 |
| `rule_types.py` | rule fallback 内部 dataclass | 业务判断 |

## LLM 路径

`route_question_llm()` 会进入同一条 pipeline，只是在 draft 阶段优先调用
`build_llm_router_draft()`。

LLM 应输出完整 `RouterOutput` draft：

```text
intent
is_compound
sub_intent_candidates
sub_intent_evidence
scenario_decisions
conditions
normalized_conditions
context_policy
requires_jd
requires_evidence
allowed_tool_names
risk_flags
```

但这些字段不是全部权威值：

- `normalized_conditions` 在 router 阶段保持空，由下一个 node 生成。
- `allowed_tool_names` 由 finalizer 根据 `tool_policy.yaml` 重算。
- `requires_jd` / `requires_evidence` 由 finalizer 根据 `intents.yaml` 和证据词重算。
- 合法的 LLM `scenario_decisions` 会保留；缺失或非法的会被规则 fallback 补齐。

## Rule Fallback 路径

`rules.py` 的阅读线是：

```text
build_rule_router_draft
-> extract_conditions
-> detect_router_signals
-> infer_rule_sub_intents
-> RULE_INTENT_HANDLERS
-> build_rule_router_output
```

`signals.py` 是侦察层，只判断文本里有什么信号：

```text
pair_compare
candidate_reference
context_policy
evidence_locator
interview_question
sensitive_interview
```

`rules.py` 是决策层，把信号变成 draft sub-intents：

```text
count terms -> candidate_count
list/profile terms -> candidate_list 或 candidate_profile_intro
evidence terms -> evidence_question
compare/ranking terms -> candidate_compare_pair 或 candidate_ranking
condition fallback -> candidate_filter
```

## Guard 路径

`guard.py` 不从零生成路由，它只纠偏 draft：

```text
apply_safety_guard
apply_intent_override_guards
  -> apply_ranking_guard
  -> apply_pair_compare_guard
  -> apply_evidence_guard
apply_compound_guard
apply_context_guard
apply_intent_convergence_guard
```

`compound_rules` 到 sub-intents 的映射在 `detect_compound_sub_intents()`：

```text
count_terms -> candidate_count
list_terms -> candidate_list
ranking_terms -> candidate_ranking
evidence_terms -> evidence_question
```

## Finalizer 权威字段

`finalizer.py` 按字段顺序收口：

```text
finalize_intent_and_sub_intents
finalize_sub_intent_evidence
finalize_scenario_decisions
finalize_conditions
finalize_requires_jd
finalize_requires_evidence
finalize_allowed_tool_names
finalize_risk_flags
```

它的原则：

- 不重新理解自然语言。
- 合法 draft scenario 保留。
- 缺失/非法 scenario 用 `scenarios.yaml.resolution_rules` 补。
- `requires_jd` / `requires_evidence` / `allowed_tool_names` / `risk_flags` 以 finalizer 为准。

## RouterOutput 字段来源表

| 字段 | Draft | Guard | Condition Completion | Finalizer |
|---|---|---|---|---|
| `intent` | LLM/rule 生成 | 可覆盖 | 不改 | 权威收口 |
| `is_compound` | LLM/rule 生成 | 可覆盖 | 不改 | 权威重算 |
| `sub_intent_candidates` | LLM/rule 生成 | 可补/覆盖 | 不改 | 权威去重 |
| `sub_intent_evidence` | LLM/rule 生成 | 通常不改 | 不改 | 缺失补齐 |
| `scenario_decisions` | LLM/rule 生成 | 不直接算 | 不改 | 校验合法，缺失/非法用 rule fallback |
| `conditions` | LLM/rule 生成 | 可间接影响 | 补齐 | 去重 |
| `normalized_conditions` | 空 | 不改 | 保持空 | 保持空 |
| `context_policy` | LLM/rule 生成 | 可覆盖 | 不改 | 保留 |
| `requires_jd` | 初稿 | 可提示 | 不改 | 权威重算 |
| `requires_evidence` | 初稿 | 可提示 | 不改 | 权威重算 |
| `allowed_tool_names` | 初稿不可信 | 不改 | 不改 | 权威重算 |
| `risk_flags` | 初稿 | 追加 | 追加 | 白名单清理 |

## 示例完整走读

问题：

```text
金融候选人有几个，谁最强，依据是什么？
```

1. `preprocess_router_question`
   - 标点统一，口头前缀清理。

2. draft
   - `金融` 被抽成 `condition: domain=金融`。
   - `几个` 触发 `candidate_count`。
   - `谁最强` 触发 `candidate_ranking`。
   - `依据` 触发 `evidence_question`。

3. guard
   - `compound_rules` 确保 count/ranking/evidence 三个子任务都在。

4. condition completion
   - 补齐漏掉的 domain/skill/candidate_name/scope。

5. finalizer
   - `intent=compound`。
   - `sub_intent_candidates=[candidate_count, evidence_question, candidate_ranking]`。
   - `candidate_count -> hard_filter`。
   - `candidate_ranking -> compare_rank`。
   - `evidence_question -> evidence_lookup`。
   - `requires_jd=true`。
   - `requires_evidence=true`。

最终 RouterOutput 形状：

```json
{
  "intent": "compound",
  "sub_intent_candidates": [
    "candidate_count",
    "evidence_question",
    "candidate_ranking"
  ],
  "conditions": [
    {"type": "domain", "raw_value": "金融"}
  ],
  "requires_jd": true,
  "requires_evidence": true
}
```

## 当前保留的复杂点

- `semantic_recall` 定义在 `intents.yaml.scenario_optional_needs`，但主要给 planner/compiler 用，不是 RouterOutput 字段。
- `context_ref_rules` 是当前上下文配置；`context_references` 是旧兼容配置。
- `compound_rules` 是 YAML 词表，词表到 sub-intent 的映射仍在 `guard.py`。
- `requires_jd` / `requires_evidence` 在 draft 阶段也可能出现，但 finalizer 才是权威值。
