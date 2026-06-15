# Executor Node

一句话：`executor` 接收已经通过校验的 `QueryPlan`，按顺序调用只读工具，并把工具返回包装成 `ToolResult[]`。

## 架构位置

```text
plan_compiler
-> plan_validator
-> executor
-> execution_validator
-> aggregator
```

如果执行结果不满足合同，后续路线是：

```text
execution_validator -> execution_repair / clarification / fail
```

`executor` 不是规划层，也不是质量判断层。它只负责把已经验证过的 `ToolCallSpec` 真正调用出去。

## 节点目标

`executor` 做三件事：

- 按 `QueryPlan.tool_calls` 或 `QueryPlan.sub_tasks[].tool_calls` 的顺序执行工具。
- 在每次调用前解析参数里的 `$ref`，把前面工具的输出传给后面工具。
- 调用 `tools/registry.py` 中注册的只读工具，并把结果统一包装成 `ToolResult`。

## 输入

| 输入 | 来源 | 用途 |
|---|---|---|
| `QueryPlan` | `plan_compiler` 生成，`plan_validator` 放行 | 提供最终工具名、参数、依赖、输出 key。 |
| `session_context` | graph state | 注入给 `resolve_candidate_reference` 这类需要上下文的工具。 |
| `ResumeQAConfig` | graph state / `load_config()` | 读取 executor runtime retry 次数。 |
| tool registry | `resume_query_ai_qa.tools.get_tool_registry()` | 根据 `ToolCallSpec.name` 找到实际 Python 函数。 |
| previous tool outputs | executor 内部 `tool_context` | 解析 `$ref` 引用。 |

## 输出

| 输出 | 去向 | 用途 |
|---|---|---|
| `ToolResult[]` | `execution_validator` | 检查工具结果是否满足 plan / router 语义。 |
| `ToolResult[]` | `aggregator` | 后续回答只能基于工具事实生成。 |
| `tool_results_summary` | trace | 展示每个工具 ok / failed 状态。 |

## 它做什么

- 执行 `QueryPlan` 中已经存在的工具调用。
- 支持普通 `$ref`，例如 `$candidate_pool.resume_identity[]`。
- 支持结构化 `$ref`，例如 `{"$ref": "candidate_pool", "path": ["resume_identity"], "map": true}`。
- 对工具 runtime exception 做有限重试。
- 把 unknown tool、参数绑定失败、业务错误、异常都包装成 failed `ToolResult`。

## 它不做什么

- 不生成新的 `ToolCallSpec`。
- 不修复非法 `QueryPlan`。
- 不判断结果是否足够回答用户问题。
- 不扩大候选人范围。
- 不回答用户。
- 不隐藏工具失败。

## `$ref` 参数绑定机制

executor 会维护一个内部字典：

```python
tool_context = {
    "candidate_pool": <filter_candidates 的结果>,
    "candidate_count": <count_candidates 的结果>,
}
```

当后续工具参数里出现：

```python
"candidate_ids": "$candidate_pool.resume_identity[]"
```

executor 会从 `tool_context["candidate_pool"]` 里取出每个候选人的 `resume_identity`，变成真实参数：

```python
"candidate_ids": ["resume_001", "resume_008"]
```

所以 `$ref` 不是 YAML 直接变函数参数，而是：

```text
plan_compiler 写入引用
-> executor 执行前读取前序 ToolResult
-> binding.py 把引用替换成真实值
-> retry.py 调用实际工具函数
```

## 工具调用与错误

`retry.py` 统一处理四类结果：

| 场景 | 行为 |
|---|---|
| argument binding failed | 不调用工具，直接返回 failed `ToolResult`。 |
| unknown tool | 不调用工具，直接返回 failed `ToolResult`。 |
| business error | 保留工具返回的业务错误和用户提示，不做 runtime retry。 |
| runtime exception | 按 `validation.yaml.retry_limits.executor_tool_call` 有限重试。 |

business error 指工具正常运行，但业务上不可满足，比如候选人引用无法解析。runtime exception 指工具函数抛出异常，比如代码错误或临时 IO 失败。

executor 的失败处理心智模型：

```text
executor 不抛异常中断整条链
executor 把失败包装成 ToolResult
后面的 execution_validator 再判断这个失败该 fail / repair / clarify
```

也就是说，executor 只负责“把工具执行结果如实交出去”。失败是否可修复、是否需要澄清、是否直接失败，不在 executor 判断，而是在 `execution_validator` 和后续 graph route 判断。

## 示例

问题：

```text
金融候选人有几个，谁最强，依据是什么？
```

进入 executor 前，`plan_compiler` 已经生成类似计划：

```text
filter_candidates(domains_any=["金融"]) -> candidate_pool
count_candidates(candidate_ids=$candidate_pool.resume_identity[]) -> candidate_count
load_default_jd_criteria() -> jd_criteria
score_candidates_for_jd(candidate_ids=$candidate_pool.resume_identity[], criteria=$jd_criteria) -> candidate_scores
rank_candidates(scores=$candidate_scores) -> ranked_candidates
search_candidate_evidence(candidate_ids=$ranked_candidates.resume_identity[]) -> candidate_evidence
```

executor 的执行过程：

```text
1. 调用 filter_candidates，结果保存为 candidate_pool
2. 调用 count_candidates 前，把 $candidate_pool.resume_identity[] 解析成候选人 id 列表
3. 调用 load_default_jd_criteria，结果保存为 jd_criteria
4. 调用 score_candidates_for_jd 前，解析 candidate ids 和 criteria
5. 调用 rank_candidates，得到排序结果
6. 调用 search_candidate_evidence 前，从排序结果里解析候选人 id
7. 返回所有 ToolResult
```

executor 不决定“金融”从哪里来，也不决定“谁最强”该用什么工具。这些已经由 router / condition_normalizer / planner / compiler / validator 完成。

## 文档阅读顺序

```text
1. README.md
2. EXECUTOR_FLOW.md
3. YAML_USAGE.md
4. node.py
5. binding.py
6. retry.py
```

## 验收命令

```bash
rg "Executor Node|EXECUTOR_FLOW|YAML_USAGE|ToolResult|execute_plan_with_context|bind_argument_refs" resume_query_ai_qa/nodes/executor
./.venv/bin/python -m compileall -q resume_query_ai_qa/nodes/executor
./.venv/bin/python resume_query_ai_qa/benchmarks/run_policy_contract_benchmark.py
./.venv/bin/python resume_query_ai_qa/benchmarks/run_plan_contract_benchmark.py
./.venv/bin/python resume_query_ai_qa/benchmarks/run_runtime_contract_benchmark.py
```
