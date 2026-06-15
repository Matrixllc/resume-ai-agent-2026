# Execution Repair Flow

这个文档按代码阅读顺序讲 `execution_repair`。

核心输入输出：

```text
execution errors + ToolResult[] + QueryPlan + RouterOutput
-> repaired QueryPlan + repair decision
```

## 1. `classify_execution_repair_action`

入口之一。graph route 和 repair node 都会调用它。

作用：

```text
根据 execution validation issue 判断下一步是 clarify / fail / query_fallback。
```

流程：

```text
errors -> validation_issues
-> validation_action(config, issues, "execution")
-> 如果 action=clarify，直接返回
-> 如果 issue code 包含 empty_retrieval，检查是否允许 query_fallback
-> 否则返回 validation.yaml 的默认 action
```

query fallback 必须同时满足：

```text
1. issue code = empty_retrieval
2. plan 对应的 scenario 是 open_recall
3. plan 里存在配置了 fallback_tool 的工具调用
```

如果是 empty retrieval 但不满足这些条件，则返回：

```text
action=fail
reason=structured_empty_result_should_not_recall
```

## 2. `repair_execution_plan`

真正生成 repaired `QueryPlan` 的入口。

作用：

```text
根据 classify_execution_repair_action 的结果决定是否改写 plan。
```

流程：

```text
decision = classify_execution_repair_action(...)

if action in {clarify, fail}:
    return 原 plan

if action == query_fallback:
    repaired = _fallback_recall_plan(...)
    repaired = with_structured_refs(repaired)
    repaired = with_artifact_bindings(repaired, router_output)
    return repaired
```

为什么要刷新 refs / artifacts：

```text
fallback 可能替换了工具名和产物来源。
重新生成 refs 和 artifact bindings 后，plan_validator 才能检查新计划是否合法。
```

## 3. `_allows_query_fallback`

作用：

```text
检查当前 plan 的 intent 是否存在 open_recall scenario。
```

它通过：

```text
scenario_for_intent(router_output, intent)
```

读取 router 已经收口好的 scenario。

只有 open_recall 才允许 fallback recall。hard_filter 空结果不允许在这里扩大召回。

## 4. `_fallback_recall_plan`

作用：

```text
对普通 plan 或 compound plan 应用 query fallback。
```

它先生成 fallback query：

```text
cleaned_retrieval_query(router_output.normalized_conditions, fallback=question)
```

如果条件里能清洗出更适合召回的 query，就用清洗后的；否则用原始问题。

普通 plan：

```text
plan.tool_calls -> _fallback_calls(...)
```

compound plan：

```text
plan.sub_tasks[].tool_calls -> _fallback_compound_plan(...)
```

如果没有替换到任何工具，但 action 是 `query_fallback`，会插入默认 fallback tool。

## 5. `_fallback_compound_plan`

作用：

```text
对 compound plan 的每个 sub_task 分别尝试 fallback call 替换。
```

它不改变 sub_task 的 intent，只替换里面符合条件的 tool call。

## 6. `_fallback_calls`

核心替换函数。

输入：

- 原 `ToolCallSpec[]`
- fallback query
- action
- config

逻辑：

```text
for call in calls:
    fallback_tool = tool_policy.yaml.tools[call.name].fallback_tool
    if action == query_fallback and fallback_tool:
        replace call.name with fallback_tool
        arguments = {"query": query}
        if 原 call 有 candidate_ids:
            保留 candidate_ids
        保留 output_key / depends_on / purpose / expected_output
    else:
        原 call 保留
```

例子：

```text
filter_candidates(domains_any=["金融风控"]) -> candidate_pool
```

替换为：

```text
hybrid_search_candidates(query="金融风控") -> candidate_pool
```

保留同一个 `output_key` 的原因：

```text
后续工具仍然可以通过同一个 artifact / output_key 引用候选人集合。
```

## 7. `_default_fallback_tool`

作用：

```text
当需要 query_fallback 但原 calls 没有替换成功时，找一个默认 fallback tool 插入。
```

来源：

```text
tool_policy.yaml.tools.*.fallback_tool
```

如果配置里完全没有 fallback tool，会抛：

```text
tool_policy.yaml must configure at least one fallback_tool
```

## 8. `_iter_plan_calls`

作用：

```text
把普通 plan 或 compound plan 的 tool calls 展平成列表。
```

用于 `_has_tool_call()` 判断 plan 中是否存在某个工具。

## 9. `_has_tool_call`

作用：

```text
判断当前 QueryPlan 是否包含指定工具调用。
```

在分类阶段用于确认：

```text
原 plan 里是否有可以被 fallback_tool 替换的工具。
```

## Graph Route

执行修复的图路径：

```text
execution_validator
-> route_after_execution_validation
-> execution_repair
-> plan_validator
-> executor
```

为什么 repair 后回 `plan_validator`：

```text
execution_repair 改了 QueryPlan。
任何改过的 QueryPlan 都必须重新校验工具权限、参数、依赖和 artifact binding。
```

## 示例：open_recall 空候选

问题：

```text
找找可能和金融风控相关的人
```

原计划：

```text
filter_candidates(domains_any=["金融风控"]) -> candidate_pool
```

执行结果：

```text
filter_candidates ok -> []
```

execution_validator：

```text
filter_candidates returned no candidates
```

execution_repair：

```text
classify_execution_repair_action -> query_fallback
_fallback_calls:
  filter_candidates -> hybrid_search_candidates
  arguments -> {"query": "金融风控"}
  output_key -> candidate_pool
```

修复后计划：

```text
hybrid_search_candidates(query="金融风控") -> candidate_pool
```

然后回：

```text
plan_validator
```
