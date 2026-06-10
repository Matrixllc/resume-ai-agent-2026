# Execution Repair Node

## 职责

`execution_repair` 处理工具执行后“结果不足但可安全 fallback”的少数场景。它产出
repaired `QueryPlan`，然后回到 `plan_validator` 复核。

## 输入

| 输入 | 来源 | 用途 |
|---|---|---|
| execution errors | execution_validator | 分类是否可 repair。 |
| `ToolResult[]` | executor | 判断空候选、工具失败等。 |
| current `QueryPlan` | graph state | 局部替换可 fallback 的 tool call。 |
| `RouterOutput` | graph state | 判断是否 open recall。 |

## 输出

| 输出 | 用途 |
|---|---|
| repaired `QueryPlan` | 回到 plan_validator。 |
| `repair_action` | Debug 展示。 |
| `repair_reason` | 为什么修。 |
| `error_category` | 错误分类。 |

## 主流程

```text
execution errors
-> classify_execution_repair_action
-> query_fallback only when open recall empty candidates
-> refresh artifact bindings
-> plan_validator
```

## 允许的 Repair

| 动作 | 条件 | 说明 |
|---|---|---|
| `query_fallback` | open recall 空候选且原 plan 有 `filter_candidates` | 替换为受 scope 约束的 recall source。 |

## 不允许 Repair

| 场景 | 行为 |
|---|---|
| hard filter 空结果 | aggregator 回答空结果，不扩大召回。 |
| evidence 正常返回 0 条 | aggregator 回答不能确认，记录 `empty_evidence` warning。 |
| 工具内部异常 | fail。 |
| 参数绑定失败 | fail。 |
| candidate lineage 逃逸 | fail。 |
| 单候选引用失败 | fail。 |

## Trace 字段

- `decision_steps[].node=execution_repair`
- `repair_action`
- `repair_reason`
- `error_category`
- `previous_errors`
- `route_events[]`

## 边界：能做 / 不能做

能做：

- 在 open recall 空候选时做受控 query fallback。
- 保持 candidate scope、root 和 lineage。
- 回到 plan_validator。

不能做：

- 不处理 evidence 空结果。
- 不放宽 hard filter。
- 不调用工具。
- 不直接进入 aggregator。

## 扩展方式

新增 execution repair 必须先回答：

1. 它是否扩大候选人集合。
2. 哪个 scenario 允许。
3. 修复后哪个 validator 能证明安全。
4. 如何在 trace 中解释。

## 验收 benchmark

```bash
.venv/bin/python resume_query_ai_qa/benchmarks/run_runtime_contract_benchmark.py
.venv/bin/python resume_query_ai_qa/benchmarks/run_runtime_contract_benchmark.py
```
