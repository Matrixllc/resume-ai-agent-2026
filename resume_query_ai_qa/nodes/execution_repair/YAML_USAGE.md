# Execution Repair YAML Usage

`execution_repair` 的 YAML 使用目标是：判断执行失败是否可以安全修复，以及用哪个 fallback tool 修复。

它不是通用修复器。当前只处理：

```text
open_recall + empty_retrieval + fallback_tool
```

## 直接使用

### `validation.yaml.issue_actions`

使用位置：

```text
node.py -> classify_execution_repair_action()
behavior_contract.validation_action()
```

作用：

```text
先根据 ValidationIssue 决定默认 action：repair / clarify / fail。
```

相关配置：

```yaml
issue_actions:
  codes:
    empty_retrieval:
      action: repair
      reason: candidate_retrieval_empty
    tool_failure:
      action: fail
      reason: tool_internal_error
    argument_binding:
      action: fail
      reason: argument_binding_error
```

含义：

```text
empty_retrieval 默认可 repair
工具异常和参数绑定失败默认 fail
```

但是 execution_repair 还会继续检查 scenario 和 fallback_tool。不是所有 empty_retrieval 都真的会修。

### `validation.yaml.legacy_issue_classifiers`

使用位置：

```text
validation_issues(errors, "execution")
```

作用：

```text
当 validator 只给了 error string 时，把字符串分类成结构化 ValidationIssue。
```

相关配置：

```yaml
legacy_issue_classifiers:
  - code: empty_retrieval
    category: retrieval
    contains_any: [returned no candidates]
```

含义：

```text
错误文本里包含 returned no candidates，就可被归类为 empty_retrieval。
```

### `tool_policy.yaml.tools.*.fallback_tool`

使用位置：

```text
classify_execution_repair_action()
_fallback_calls()
_default_fallback_tool()
```

作用：

```text
决定哪个工具可以被替换成 fallback recall 工具。
```

当前典型配置：

```yaml
filter_candidates:
  fallback_tool: hybrid_search_candidates
```

含义：

```text
filter_candidates 在允许 fallback 的场景下，可以替换为 hybrid_search_candidates。
```

## 通过对象 / helper 间接使用

### `RouterOutput.scenario_decisions`

使用位置：

```text
_allows_query_fallback()
scenario_for_intent(router_output, intent)
```

作用：

```text
判断当前 intent 是否是 open_recall。
```

只有 open_recall 才允许 query fallback。

对比：

```text
open_recall 空结果：可以尝试更开放召回
hard_filter 空结果：不扩大召回，应该回答没有找到
```

### `condition_rules` / condition cleaning

使用位置：

```text
_fallback_recall_plan()
cleaned_retrieval_query(router_output.normalized_conditions, fallback=question)
```

作用：

```text
从 normalized_conditions 中清洗出更适合召回的 query。
如果清洗失败，就使用原始 question。
```

例子：

```text
原问题：找找可能和金融风控相关的人
fallback query：金融风控
```

## 不是本节点负责的 YAML

### `tool_policy.yaml.intent_tools`

主要使用者：

```text
plan_compiler / plan_validator
```

execution_repair 不重新选择任意工具，只使用原工具配置的 `fallback_tool`。

### `evidence_policy.yaml`

主要使用者：

```text
execution_validator / aggregator / answer_validator
```

execution_repair 当前不修 evidence 空结果。

### `compiler_templates.yaml`

主要使用者：

```text
plan_compiler
```

execution_repair 不重新编译 workflow template，只局部替换 tool call。

## 小结

execution_repair 的 YAML 心智模型：

```text
validation.yaml:
  empty_retrieval 是否被分类为可 repair

tool_policy.yaml:
  哪些工具有 fallback_tool
  fallback_tool 是哪个

RouterOutput:
  当前 scenario 是否 open_recall

condition cleaning:
  fallback query 应该用什么文本
```

最终安全条件：

```text
只有 open_recall + empty_retrieval + fallback_tool 同时满足，才生成 query_fallback repaired plan。
```
