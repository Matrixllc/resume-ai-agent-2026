# Condition Normalizer Node

## 职责

`condition_normalizer` 把 router 输出的原始 `conditions` 转成下游稳定消费的
`normalized_conditions`。它是条件权威收口层。

## 输入

| 输入 | 来源 | 用途 |
|---|---|---|
| `RouterOutput.conditions` | router | 原始领域、技能、范围、候选人等条件。 |
| `question` | 用户请求 | conditions 缺失时做 rule fallback 抽取。 |
| taxonomy/config | `core.rules.condition_rules` | domain/skill/concept 归一化。 |

## 输出

| 输出 | 用途 |
|---|---|
| `RouterOutput.conditions` | 补齐后的原始条件。 |
| `RouterOutput.normalized_conditions` | 标准条件，供 policy、compiler、validator、aggregator 使用。 |

## 主流程

```text
读取 router_output.conditions
-> 条件为空时 extract_conditions(question)
-> normalize_conditions(...)
-> mark_preference_targets(...)
-> 写回 RouterOutput
```

## 失败 / Fallback

| 场景 | 行为 | Trace 字段 |
|---|---|---|
| router 未给 conditions | rule extract fallback | `summary=normalized_conditions=N` |
| 未命中 taxonomy | 保留低置信度或原始值 | `warnings` |
| preference target | 标记为目标条件，避免误硬筛 | `normalized_conditions[].matched_by` |

## Trace 字段

- `decision_steps[].node=condition_normalizer`
- `summary=normalized_conditions=...`
- `normalized_conditions[].type`
- `normalized_conditions[].normalized_value`
- `normalized_conditions[].retrieval_terms`

## 边界：能做 / 不能做

能做：

- 提取和标准化条件。
- 统一 domain/skill/concept/scope 表达。
- 标记 preference target。

不能做：

- 不改 intent。
- 不计算 scenario。
- 不选工具。
- 不调用 tools。
- 不生成答案。

## 扩展方式

- 新领域/概念：优先更新 taxonomy/config。
- 新条件类型：补 `QueryCondition`、normalizer、compiler/validator 消费逻辑。
- 新匹配规则：放入 `core.rules.condition_rules`，不要写在前端或 aggregator。

## 验收 benchmark

```bash
.venv/bin/python resume_query_ai_qa/benchmarks/run_plan_contract_benchmark.py
.venv/bin/python resume_query_ai_qa/benchmarks/run_policy_contract_benchmark.py
```
