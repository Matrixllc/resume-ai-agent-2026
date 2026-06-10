# Plan Validator Node

## 职责

`plan_validator` 是执行前的只读计划闸门。它检查 `QueryPlan` 是否能安全执行，
也负责复核 `plan_repair` 和 `execution_repair` 产出的 repaired plan。

## 输入

| 输入 | 来源 | 用途 |
|---|---|---|
| `QueryPlan` | plan_compiler / repair | 被校验对象。 |
| `RouterOutput` | router/normalizer | intent、conditions、context policy。 |
| `ExecutionDecision` | execution_policy | scenario 和 workflow 约束。 |
| `session_context` | graph state | 判断上下文引用是否存在。 |
| tool registry | registry | 检查工具名和参数签名。 |

## 输出

| 输出 | 用途 |
|---|---|
| `ValidationResult.ok` | graph route 到 executor 或 repair/fail。 |
| `errors[]` | plan 阻塞错误。 |
| `warnings[]` | 可解释但不阻塞的问题。 |
| trace meta | API diagnosis 和 Debug 面板使用。 |

## 主流程

```text
QueryPlan
-> structure validation
-> tool existence/signature
-> depends_on / $ref validation
-> artifact/source contract
-> semantic scenario validation
-> context availability
```

## 失败 / Repair

| 场景 | 行为 | Trace 字段 |
|---|---|---|
| 工具不存在/参数非法 | fail 或 plan_repair | `validation_errors.plan` |
| hard_filter 使用 query-only hybrid | fail | `semantic:*` |
| 缺 last_candidate/candidate_pool/ranking_top | clarify | `required_context_missing` |
| 可规则修复 plan mismatch | `plan_repair -> plan_validator` | `repair_action` |
| repair 超限 | fail | `route_events.reason=plan_repair_limit_exceeded` |

## Trace 字段

- `decision_steps[].node=plan_validator`
- `status=ok|failed`
- `errors`
- `warnings`
- `validation_errors.plan`
- `route_events[]`
- `diagnosis.failed_node=plan_validator`

## 边界：能做 / 不能做

能做：

- 拦截非法工具、非法参数、非法 source。
- 检查 context 是否足够。
- 检查 hard/open scenario 契约。

不能做：

- 不调用工具。
- 不修工具结果。
- 不重新 compiler。
- 不生成答案。

## 扩展方式

- 新工具参数：同步 registry signature 和 validator。
- 新 scenario：补 semantic/source contract。
- 新 artifact：补 artifact contract 和 debug benchmark。

## 验收 benchmark

```bash
.venv/bin/python resume_query_ai_qa/benchmarks/run_plan_contract_benchmark.py
.venv/bin/python resume_query_ai_qa/benchmarks/run_runtime_contract_benchmark.py
```
