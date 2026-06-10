# Executor Node

## 职责

`executor` 是唯一调用 Query-AI 只读 tools 的 graph node。它接收已经通过
`plan_validator` 的 `QueryPlan`，按依赖顺序执行工具，并把结果包装成
`ToolResult[]`。

## 输入

| 输入 | 来源 | 用途 |
|---|---|---|
| validated `QueryPlan` | plan_validator | 工具调用计划。 |
| `session_context` | graph state | 传给 `resolve_candidate_reference` 等需要上下文的工具。 |
| tool registry | registry | 查找可执行工具函数。 |
| previous tool outputs | executor context | 解析 `$ref` 参数。 |

## 输出

| 输出 | 用途 |
|---|---|
| `ToolResult[]` | execution_validator 和 aggregator 消费。 |
| `tool_results_summary` | trace 展示工具状态、shape、数量。 |
| failed `ToolResult` | 后续 validator 分类系统/业务错误。 |

## 主流程

```text
QueryPlan
-> 按 tool_calls 或 sub_tasks 顺序执行
-> resolve $ref arguments
-> call registered read-only tool
-> wrap data / warnings / business error / exception
-> ToolResult[]
```

## 失败 / Retry

| 场景 | 行为 | Trace 字段 |
|---|---|---|
| unknown tool | failed ToolResult | `tools[].status=failed` |
| `$ref` 绑定失败 | failed ToolResult | `error=argument binding failed` |
| 工具抛异常 | bounded runtime retry | retry 后仍失败进入 execution_validator |
| 工具返回 business error | ToolResult 保留业务错误 | execution_validator/aggregator 分类 |

## Trace 字段

- `decision_steps[].node=executor`
- `summary=tools=N`
- `tools[].name`
- `tools[].status`
- `tools[].error`
- `tools[].warnings`

## 边界：能做 / 不能做

能做：

- 调用 registry 中的只读工具。
- 解析 `$ref` 和结构化 `$ref`。
- 包装工具异常、warning 和业务错误。

不能做：

- 不判断工具结果是否足够。
- 不 repair plan。
- 不扩大候选人 scope。
- 不生成答案。
- 不隐藏工具失败。

## 扩展方式

- 新工具必须先注册 registry。
- 新 `$ref` 形态必须补 binding 逻辑和 executor contract benchmark。
- 工具异常 retry 只处理 runtime exception，不处理业务空结果。

## 验收 benchmark

```bash
.venv/bin/python resume_query_ai_qa/benchmarks/run_runtime_contract_benchmark.py
.venv/bin/python resume_query_ai_qa/benchmarks/run_runtime_contract_benchmark.py
```
