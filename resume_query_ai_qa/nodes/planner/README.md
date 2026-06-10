# Planner Node

## 职责

`planner` 只在 generic 路径运行。它把 question、`RouterOutput` 和
`ExecutionDecision` 转成 `SemanticPlan`，描述“语义上需要做什么”。

Planner 不生成可执行工具计划。

## 输入

| 输入 | 来源 | 用途 |
|---|---|---|
| `question` | 用户请求 | 语义步骤描述。 |
| `RouterOutput` | router/normalizer | intent、conditions、context policy。 |
| `ExecutionDecision` | execution_policy | scenarios、planner engine。 |
| `tool_policy.yaml` | config | tool capability hint。 |

## 输出

| 输出 | 用途 |
|---|---|
| `SemanticPlan.intent` | compiler 降级入口。 |
| `SemanticPlan.steps[]` | 每个子任务的 semantic needs。 |
| `tool_hints` / `tool_hint_scores` | compiler 可接受或拒绝的建议。 |
| `context_policy` | 下游 compiler/validator 绑定上下文。 |
| trace meta | 记录 rule/LLM/fallback。 |

## 主流程

```text
ExecutionDecision.planner = rule
-> semantic_plan_from_router()

ExecutionDecision.planner = llm
-> LLM SemanticPlan draft
-> authority normalize
-> fallback to rule when disabled/error
```

## 失败 / Fallback

| 场景 | 行为 | Trace 字段 |
|---|---|---|
| LLM disabled | rule fallback | `engine=rule_fallback`、`fallback_reason=llm_disabled` |
| LLM error/schema error | rule fallback | `fallback_reason` |
| LLM 越权改 intent/conditions | authority normalize 覆盖 | `SemanticPlan` 以 Router/Policy/YAML 为权威 |

## Trace 字段

- `decision_steps[].node=planner`
- `engine=llm|rule|rule_fallback`
- `fallback_reason`
- `semantic_plan.steps[]`
- `tool_hint_scores[]`

## 边界：能做 / 不能做

能做：

- 描述 semantic needs。
- 给出白名单内 tool hints 和 reason。
- 使用 LLM 帮助开放问题泛化。

不能做：

- 不生成 `ToolCallSpec`。
- 不拼 `$ref`、`depends_on`、`output_key`。
- 不调用工具。
- 不建立 artifact lineage。
- 不生成答案。

## 扩展方式

- 新 generic 能力：先更新 `tool_policy.yaml` capability，再补 planner benchmark。
- 新 LLM prompt：必须保留 authority normalize 和 rule fallback。
- 新 semantic need：同步 compiler 消费和 validator 契约。

## 验收 benchmark

```bash
.venv/bin/python resume_query_ai_qa/benchmarks/run_plan_contract_benchmark.py
.venv/bin/python resume_query_ai_qa/benchmarks/run_plan_contract_benchmark.py
```
