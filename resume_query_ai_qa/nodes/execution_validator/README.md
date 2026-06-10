# Execution Validator Node

## 职责

`execution_validator` 是工具执行后的结果合同闸门。它只读 `QueryPlan` 和
`ToolResult[]`，判断工具结果是否足够、是否一致、是否越界。

## 输入

| 输入 | 来源 | 用途 |
|---|---|---|
| `QueryPlan` | plan_compiler/repair | 判断 intent 需要哪些结果。 |
| `ToolResult[]` | executor | 检查工具状态、数量、lineage。 |
| `RouterOutput` | graph state | 判断 hard/open/fact_check 语义。 |
| `session_context` | graph state | 检查 candidate pool / ranking lineage。 |

## 输出

| 输出 | 用途 |
|---|---|
| `ValidationResult.ok` | graph route 到 aggregator 或 repair/fail。 |
| `errors[]` | 阻塞错误。 |
| `warnings[]` | 可解释 warning。 |
| `next_node` | route 使用。 |

## 主流程

```text
ToolResult[]
-> failed tool classification
-> required result check
-> evidence coverage warning/error
-> count / compare consistency
-> empty retrieval policy
-> candidate lineage check
```

## 失败 / Repair / Warning

| 场景 | 行为 | Trace 字段 |
|---|---|---|
| 工具内部异常 | fail | `validation_errors.execution` |
| 参数绑定失败 | fail | `error_category=binding` |
| hard filter 空结果 | ok，交给 aggregator 回答空结果 | no repair |
| open recall 空候选 | 可进入 `execution_repair -> query_fallback` | `repair_action=query_fallback` |
| evidence 正常返回 0 条 | ok，交给 aggregator 回答不能确认 | `empty_evidence:*` warning |
| count/list 不一致 | fail | `count mismatch` |
| candidate lineage 逃逸 | fail | `lineage escape` |
| 双人比较不足 2 人 | clarification | `comparison_pair_missing` |

## Trace 字段

- `decision_steps[].node=execution_validator`
- `status=ok|failed`
- `errors`
- `warnings`
- `validation_errors.execution`
- `route_events[].reason`
- `diagnosis.failed_node=execution_validator`

## 边界：能做 / 不能做

能做：

- 判定工具结果是否满足契约。
- 区分业务空结果和系统失败。
- 保护 candidate lineage。

不能做：

- 不调用工具。
- 不修 plan。
- 不写答案。
- 不把 hard filter 空结果扩大召回。

## 扩展方式

- 新工具结果形态：补 required result 和 result shape 检查。
- 新空结果策略：先定义 scenario，再补 validator contract。
- 新 lineage：补 `execution_lineage.py` 和 benchmark。

## 验收 benchmark

```bash
.venv/bin/python resume_query_ai_qa/benchmarks/run_runtime_contract_benchmark.py
.venv/bin/python resume_query_ai_qa/benchmarks/run_plan_contract_benchmark.py
```
