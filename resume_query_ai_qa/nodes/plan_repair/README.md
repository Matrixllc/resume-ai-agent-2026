# Plan Repair Node

## 职责

`plan_repair` 处理执行前的非法 `QueryPlan`。它根据 `plan_validator` 错误分类做
确定性 rebuild 或局部 patch，然后回到 `plan_validator`。

默认不启用 LLM repair；LLM repair 只作为实验辅助保留。

## 输入

| 输入 | 来源 | 用途 |
|---|---|---|
| invalid `QueryPlan` | plan_validator | 被修复计划。 |
| `plan_errors[]` | plan_validator | 分类 repair/fail/clarify。 |
| `RouterOutput` | graph state | 重新构造计划时使用权威 intent/conditions。 |
| `session_context` | graph state | context ref 修复和复核。 |

## 输出

| 输出 | 用途 |
|---|---|
| repaired `QueryPlan` | 回到 plan_validator。 |
| `repair_action` | Debug 和 diagnosis。 |
| `repair_reason` | 说明为什么修。 |
| `error_category` | 错误分类。 |

## 主流程

```text
plan_errors
-> classify_plan_repair_action
-> rule rebuild / patch
-> refresh artifact bindings
-> plan_validator
```

## 失败 / Repair

| 场景 | 行为 | Trace 字段 |
|---|---|---|
| semantic plan mismatch 可修 | rule repair | `repair_action`、`repair_reason` |
| 缺上下文 | fail | `error_category=context_missing` |
| 工具/source contract 不可修 | fail | `validation_errors.plan` |
| repair 后仍非法 | 回 plan_validator 再分类 | `route_events` |

## Trace 字段

- `decision_steps[].node=plan_repair`
- `repair_action`
- `repair_reason`
- `error_category`
- `previous_errors`

## 边界：能做 / 不能做

能做：

- 在不放宽安全边界的前提下修复计划。
- 刷新 artifact bindings。
- 回到 validator 复核。

不能做：

- 不调用 tools。
- 不直接进入 executor。
- 不忽略 validator 错误。
- 不用 repair 掩盖缺上下文。

## 扩展方式

新增 repair 前必须定义：

1. 哪类 validator error 可修。
2. 修复是否会扩大 candidate scope。
3. 修复后哪个 validator contract 证明安全。
4. 对应 bad case benchmark。

## 验收 benchmark

```bash
.venv/bin/python resume_query_ai_qa/benchmarks/run_runtime_contract_benchmark.py
.venv/bin/python resume_query_ai_qa/benchmarks/run_runtime_contract_benchmark.py
```
