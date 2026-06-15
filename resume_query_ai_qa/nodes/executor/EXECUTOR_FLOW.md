# Executor Flow

这个文档按代码阅读顺序讲 executor。重点是看懂：

```text
QueryPlan -> ToolCallSpec -> 参数引用绑定 -> 工具调用 -> ToolResult
```

## 1. `execute_plan_with_context`

入口之一，用在 graph 节点里。

输入：

- `plan: QueryPlan`
- `session_context: dict | None`
- `config: ResumeQAConfig | None`

输出：

- `list[ToolResult]`

它只额外处理一种情况：如果工具是 `resolve_candidate_reference`，并且参数里还没有 `session_context`，就把当前会话上下文塞进去。

为什么这么做：

```text
“第一名 / 这些人 / 刚才那个人”这类问题需要上一轮上下文。
但普通工具不需要 session_context，所以只给 resolve_candidate_reference 注入。
```

然后它会用 `plan_with_calls()` 重建 plan，再交给 `execute_plan()`。

## 2. `execute_plan`

核心执行循环。

流程：

```text
load config
create tool_context = {}
for call in iter_tool_calls(plan):
    executable_call = bind_argument_refs(call, tool_context)
    result = execute_tool_call(executable_call)
    results.append(result)
    if result.ok and call.output_key:
        tool_context[call.output_key] = result.data
return results
```

这里的关键是 `tool_context`。

它保存每个成功工具调用的输出：

```python
{
    "candidate_pool": filter_candidates 的 data,
    "candidate_count": count_candidates 的 data,
}
```

后面的工具可以通过 `$candidate_pool.xxx` 引用前面的结果。

## 3. `iter_tool_calls`

从 `QueryPlan` 中按执行顺序取出工具调用。

普通 plan：

```text
plan.tool_calls
```

复合 plan：

```text
plan.sub_tasks[0].tool_calls
plan.sub_tasks[1].tool_calls
...
```

它不排序、不校验依赖，只按 compiler 已经写好的顺序展开。

## 4. `bind_argument_refs`

把 `ToolCallSpec.arguments` 里的引用替换成真实值。

例子：

```python
ToolCallSpec(
    name="count_candidates",
    arguments={"candidate_ids": "$candidate_pool.resume_identity[]"},
)
```

如果 `tool_context["candidate_pool"]` 是：

```python
[
    {"resume_identity": "resume_001", "name": "张三"},
    {"resume_identity": "resume_008", "name": "李四"},
]
```

绑定后会变成：

```python
ToolCallSpec(
    name="count_candidates",
    arguments={"candidate_ids": ["resume_001", "resume_008"]},
)
```

如果绑定失败，不会抛出到 graph 外层，而是写入：

```python
{"__argument_binding_error__": "..."}
```

后面 `retry.py` 会把它转换成 failed `ToolResult`。

## 5. `resolve_refs`

递归解析任意参数值。

支持四种形态：

| 参数形态 | 行为 |
|---|---|
| 普通字符串 | 原样返回。 |
| `$candidate_pool.resume_identity[]` | 从 tool_context 读路径，`[]` 表示对列表每一项取字段。 |
| list | 递归解析每个元素。 |
| dict | 如果包含 `$ref`，走结构化引用；否则递归解析每个 value。 |

结构化引用例子：

```python
{
    "$ref": "candidate_pool",
    "path": ["resume_identity"],
    "map": True,
}
```

含义：

```text
从 candidate_pool 这个前序输出开始
对列表里的每一项取 resume_identity
```

## 6. `execute_tool_call`

执行单个 `ToolCallSpec` 的入口。

它只做一件事：

```text
load config -> execute_tool_call_with_retry(call, config)
```

真正的工具注册表、retry、错误包装都在 `retry.py`。

## 7. `execute_tool_call_with_retry`

实际调用工具函数。

流程：

```text
检查 argument binding error
-> 从 get_tool_registry() 取工具函数
-> 读取 retry limit
-> tool(**call.arguments)
-> 包装 ToolResult
```

错误处理：

| 类型 | 行为 |
|---|---|
| 参数绑定错误 | 直接 failed `ToolResult`。 |
| 未注册工具 | 直接 failed `ToolResult`。 |
| 工具返回 `__business_error__` | failed `ToolResult`，保留 data / error / warnings。 |
| 工具抛异常 | runtime retry，最后仍失败则返回异常文本。 |

## 8. `record_tool_results`

这个函数不在 executor 目录，而在 graph trace 层。

位置：

```text
resume_query_ai_qa/graph/trace_logging.py
```

它负责把 executor 产出的 `ToolResult[]` 写回：

```text
qa.tool_results
qa.trace.tool_calls
qa.trace.tool_results_summary
```

executor 本身只返回 `ToolResult[]`，graph 节点负责记录状态和 trace。

## 示例完整走读

问题：

```text
金融候选人有几个，谁最强，依据是什么？
```

executor 收到的计划类似：

```python
[
    ToolCallSpec(
        name="filter_candidates",
        arguments={"domains_any": ["金融"]},
        output_key="candidate_pool",
    ),
    ToolCallSpec(
        name="count_candidates",
        arguments={"candidate_ids": "$candidate_pool.resume_identity[]"},
        output_key="candidate_count",
    ),
    ToolCallSpec(
        name="load_default_jd_criteria",
        arguments={},
        output_key="jd_criteria",
    ),
    ToolCallSpec(
        name="score_candidates_for_jd",
        arguments={
            "candidate_ids": "$candidate_pool.resume_identity[]",
            "criteria": "$jd_criteria",
        },
        output_key="candidate_scores",
    ),
]
```

执行时：

```text
filter_candidates 先运行，产出 candidate_pool
count_candidates 运行前，candidate_ids 被绑定成真实候选人 id 列表
load_default_jd_criteria 运行，产出 jd_criteria
score_candidates_for_jd 运行前，同时绑定 candidate_ids 和 criteria
```

最后得到：

```text
ToolResult(filter_candidates)
ToolResult(count_candidates)
ToolResult(load_default_jd_criteria)
ToolResult(score_candidates_for_jd)
```

这些结果交给 `execution_validator` 检查，再交给 `aggregator` 生成回答。
