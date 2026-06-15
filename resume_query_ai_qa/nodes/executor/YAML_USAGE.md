# Executor YAML Usage

executor 直接使用的 YAML 很少。它不像 router / compiler 会大量读取规则；进入 executor 之前，绝大多数 YAML 已经被前置节点消化成 `QueryPlan`。

## 直接使用

### `validation.yaml.retry_limits.executor_tool_call`

位置：

```yaml
retry_limits:
  executor_tool_call: 2
```

使用位置：

```text
retry.py -> execute_tool_call_with_retry()
```

作用：

```text
工具函数抛 runtime exception 时，最多重试 N 次。
实际尝试次数 = executor_tool_call + 1。
```

例子：

```text
executor_tool_call: 2
```

表示：

```text
第 1 次正常调用
失败后最多再重试 2 次
总共最多 3 次
```

注意：这个 retry 只处理工具函数抛异常，不处理业务空结果。

## 间接相关，但 executor 不读取

### `tool_policy.yaml`

前置节点使用：

```text
execution_policy / plan_compiler / plan_validator
```

作用：

```text
决定某个 intent 允许哪些工具、禁止哪些工具、优先哪些工具。
```

executor 不再检查这些策略。原因是 `plan_validator` 已经在执行前检查过 `QueryPlan`。

### `compiler_templates.yaml`

前置节点使用：

```text
plan_compiler
```

作用：

```text
把 workflow template 编译成 ToolCallSpec。
例如把 filter_args / scoring_args / evidence_args 绑定到具体工具参数。
```

executor 看到的已经不是 template，而是最终 `ToolCallSpec.arguments`。

### `validation.yaml.issue_actions`

前置和后置节点使用：

```text
plan_validator / plan_repair / execution_validator / execution_repair
```

作用：

```text
决定校验失败后走 repair / clarify / fail。
```

executor 不负责路由失败，它只返回 failed `ToolResult`。后续节点会根据错误类型处理。

## 主要非 YAML 依赖

### `QueryPlan`

来源：

```text
plan_compiler
```

作用：

```text
告诉 executor 要执行哪些工具、按什么顺序执行、每个工具参数是什么。
```

### `ToolCallSpec`

关键字段：

| 字段 | executor 用途 |
|---|---|
| `name` | 去 tool registry 查找 Python 函数。 |
| `arguments` | 绑定 `$ref` 后传给工具函数。 |
| `output_key` | 工具成功后，把结果存进 `tool_context`。 |
| `depends_on` | 已在 validator 检查，executor 不重新排序。 |

### `tools/registry.py`

作用：

```text
把工具名映射到真实 Python 函数。
```

例子：

```python
{
    "filter_candidates": filter_candidates,
    "count_candidates": count_candidates,
    "rank_candidates": rank_candidates,
}
```

executor 调用方式：

```python
tool = registry.get(call.name)
data = tool(**call.arguments)
```

### `tool_context`

executor 内部临时字典，不来自 YAML。

作用：

```text
保存前序工具输出，供后序工具 `$ref` 引用。
```

例子：

```python
tool_context = {
    "candidate_pool": [
        {"resume_identity": "resume_001"},
        {"resume_identity": "resume_008"},
    ]
}
```

后序参数：

```python
"candidate_ids": "$candidate_pool.resume_identity[]"
```

绑定后：

```python
"candidate_ids": ["resume_001", "resume_008"]
```

## 小结

executor 的 YAML 心智模型可以简化成：

```text
直接使用：
  validation.yaml.retry_limits.executor_tool_call

不直接使用：
  tool_policy.yaml
  compiler_templates.yaml
  validation.yaml.issue_actions

真正输入：
  QueryPlan
  ToolCallSpec
  tool registry
  tool_context
```

也就是说，executor 不是规则解释器，而是执行器。
