# Execution Repair Node

一句话：`execution_repair` 在工具执行后，只修复少数可以安全 fallback 的执行结果问题，并把 repaired `QueryPlan` 送回 `plan_validator`。

## 架构位置

```text
executor
-> execution_validator
-> execution_repair
-> plan_validator
-> executor
```

前后节点边界：

```text
execution_validator = 发现执行结果问题
execution_repair = 只修 open_recall 空候选这类可安全 fallback 的问题
plan_validator = repair 后重新校验 QueryPlan
executor = 只执行重新验证通过的计划
```

`execution_repair` 不能绕过 `plan_validator`，也不能直接进入 `executor` 或 `aggregator`。

## 节点目标

`execution_repair` 当前只做一种受控修复：

```text
open_recall + empty_retrieval + fallback_tool
-> query_fallback
```

通俗讲：

```text
用户是在“找找可能相关的人”
结构化 filter 没找到候选人
原工具配置了 fallback_tool
才允许把结构化 filter 替换为语义召回工具
```

## 输入

| 输入 | 来源 | 用途 |
|---|---|---|
| `errors[]` | `execution_validator` | 判断当前错误是否属于可 repair 类型。 |
| `ValidationIssue[]` | `execution_validator` | 用结构化 issue code 判断 action。 |
| `ToolResult[]` | `executor` | 辅助判断空候选、工具失败等执行结果。 |
| `QueryPlan` | graph state | 在原计划上替换可 fallback 的 tool call。 |
| `RouterOutput` | graph state | 判断当前 intent/scenario 是否允许 open recall fallback。 |
| `question` | user input | fallback query 的兜底文本。 |
| `ResumeQAConfig` | graph state / `load_config()` | 读取 issue actions、fallback tool 和 output key。 |

## 输出

| 输出 | 去向 | 用途 |
|---|---|---|
| repaired `QueryPlan` | `plan_validator` | 重新检查工具、参数、引用、artifact binding。 |
| `decision.action` | graph route / trace | `query_fallback` / `clarify` / `fail`。 |
| `decision.category` | graph route / trace | 错误类别，例如 `empty_retrieval`。 |
| `decision.reason` | graph route / trace | 为什么这样处理。 |

## 它做什么

- 根据 execution validation issue 决定 repair / clarify / fail。
- 只在 open_recall 空候选时做 query fallback。
- 把配置了 `fallback_tool` 的工具调用替换为 fallback 工具。
- 保留原 tool call 的 `output_key`、`depends_on`、`purpose`、`expected_output`。
- 修复后重新刷新 structured refs 和 artifact bindings。
- 修复后必须回到 `plan_validator`。

## 它不做什么

- 不调用工具。
- 不直接进入 aggregator。
- 不修 hard_filter 空结果。
- 不修 evidence 正常返回 0 条。
- 不修工具内部异常。
- 不修参数绑定失败。
- 不修 candidate lineage 逃逸。
- 不生成答案。

## 允许的 Repair

| 动作 | 条件 | 结果 |
|---|---|---|
| `query_fallback` | `empty_retrieval` + `open_recall` + 原 plan 有配置 `fallback_tool` 的工具 | 替换为 fallback recall 工具。 |

当前典型配置：

```yaml
filter_candidates:
  fallback_tool: hybrid_search_candidates
```

因此 open_recall 下如果 `filter_candidates` 返回空，可以替换成：

```text
hybrid_search_candidates(query=cleaned_query)
```

## 不允许的 Repair

| 场景 | 行为 |
|---|---|
| hard_filter 空结果 | 不扩大召回，通常交给 aggregator 回答“没有找到”。 |
| evidence 正常返回 0 条 | 不 repair，交给 aggregator 说明没有确认依据。 |
| 工具内部异常 | 按 `validation.yaml.issue_actions` 进入 fail。 |
| 参数绑定失败 | 按 `validation.yaml.issue_actions` 进入 fail。 |
| candidate lineage 逃逸 | 不在 execution_repair 修。 |
| 单候选引用失败 | 不在 execution_repair 修。 |

## 示例

问题：

```text
找找可能和金融风控相关的人
```

router / execution_policy 判断为 open_recall。第一次计划：

```text
filter_candidates(domains_any=["金融风控"]) -> candidate_pool
```

executor 执行：

```text
filter_candidates ok -> []
```

execution_validator 报：

```text
filter_candidates returned no candidates
```

execution_repair 判断：

```text
issue code = empty_retrieval
scenario = open_recall
filter_candidates 配置了 fallback_tool
```

于是把计划修成：

```text
hybrid_search_candidates(query="金融风控") -> candidate_pool
```

然后：

```text
with_structured_refs
-> with_artifact_bindings
-> plan_validator
```

如果重新校验通过，才会再次进入 executor。

## 文档阅读顺序

```text
1. README.md
2. EXECUTION_REPAIR_FLOW.md
3. YAML_USAGE.md
4. node.py
5. __init__.py
```

## 验收命令

```bash
rg "Execution Repair|EXECUTION_REPAIR_FLOW|YAML_USAGE|repair_execution_plan|classify_execution_repair_action|query_fallback" resume_query_ai_qa/nodes/execution_repair
./.venv/bin/python -m compileall -q resume_query_ai_qa/nodes/execution_repair
./.venv/bin/python resume_query_ai_qa/benchmarks/run_policy_contract_benchmark.py
./.venv/bin/python resume_query_ai_qa/benchmarks/run_plan_contract_benchmark.py
./.venv/bin/python resume_query_ai_qa/benchmarks/run_runtime_contract_benchmark.py
```
