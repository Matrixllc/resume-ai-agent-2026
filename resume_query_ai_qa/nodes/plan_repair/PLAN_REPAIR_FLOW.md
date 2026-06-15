# Plan Repair Flow

这份文档只讲代码阅读线。YAML 字段地图看 `YAML_USAGE.md`，节点总览看 `README.md`。

## 阅读入口

```text
plan.py
-> llm.py
```

## 1. repair_plan

位置：

```text
nodes/plan_repair/plan.py
```

输入：

- `question`
- `router_output`
- `previous_plan`
- `validation_errors`
- `session_context`
- `config`
- `use_llm`
- `validation_issues`

输出：

```python
tuple[QueryPlan, dict[str, str], str, str]
```

含义：

```text
QueryPlan: repaired plan
decision: action/category/reason
engine: rule / llm / rule_fallback
fallback_reason: LLM 失败或回退原因
```

执行过程：

```text
classify_plan_repair_action
-> action in {clarify, fail} ?
   -> 保留 previous_plan，返回 terminal decision
-> 判断是否允许 LLM repair
-> 可用则 repair_llm_plan
-> LLM 失败或不可用则 build_rule_plan
-> refresh_artifact_bindings
```

## 2. classify_plan_repair_action

位置：

```text
nodes/plan_repair/plan.py
```

职责：

```text
根据 validator 错误和 validation.yaml 决定 repair / clarify / fail。
```

执行过程：

```text
validation_issues or validation_issues(errors, "plan")
-> validation_action(...)
-> 如果 action=repair，转成 action=rule_repair
```

为什么转成 `rule_repair`：

```text
graph 只需要知道要 repair；
trace/debug 需要知道本节点实际执行的是确定性规则修复。
```

## 3. build_rule_plan

位置：

```text
nodes/plan_repair/plan.py
```

职责：

```text
基于 RouterOutput 重新构建一个确定性 QueryPlan。
```

执行过程：

```text
router_output.intent == compound
-> 对每个 sub_intent 调 sub_task_for_intent
-> reuse_candidate_source_for_count_list
-> QueryPlan(intent=compound)

router_output.intent == out_of_scope
-> QueryPlan(intent=out_of_scope, notes=["out_of_scope_no_tools"])

其他
-> sub_task_for_intent(router_output.intent)
-> QueryPlan(intent=router_output.intent)
```

注意：

```text
这是安全重建，不是在坏 plan 上随意 patch。
```

## 4. requires_deterministic_plan

位置：

```text
nodes/plan_repair/plan.py
```

职责：

```text
判断哪些 intent 必须使用确定性规则计划，不允许 LLM repair。
```

当前包括：

```text
out_of_scope
candidate_count
candidate_list
candidate_profile_intro
candidate_compare_pair
compound
```

原因：

```text
这些 intent 对工具链、安全边界、候选人范围要求很硬。
```

## 5. refresh_artifact_bindings

位置：

```text
nodes/plan_repair/plan.py
```

职责：

```text
修复后重新生成 structured refs 和 artifact bindings。
```

执行：

```text
with_structured_refs
-> with_artifact_bindings
```

为什么必须做：

```text
repair 后工具调用和 output_key 可能变化，artifact binding 必须重新计算。
```

## 6. repair_llm_plan

位置：

```text
nodes/plan_repair/llm.py
```

职责：

```text
实验性 LLM QueryPlan repair。
```

默认关闭。启用条件：

```text
validation.yaml plan_repair.llm_enabled = true
use_llm = true
LLM enabled
错误类别是 semantic
previous_plan 存在
不属于 requires_deterministic_plan
```

LLM 修完仍会：

```text
with_structured_refs
-> with_artifact_bindings
-> plan_validator
```

## 7. allowed_tools_by_intent

位置：

```text
nodes/plan_repair/llm.py
```

职责：

```text
给 LLM repair prompt 暴露每个 intent 允许使用的工具。
```

来源：

```text
tool_policy.yaml allowed_tools / forbidden_tools
RouterOutput.scenario_decisions
```

## 8. tool_specs

位置：

```text
nodes/plan_repair/llm.py
```

职责：

```text
把 tool registry 的函数参数名提供给 LLM prompt。
```

注意：

```text
这只是 prompt 约束。最终仍要回 plan_validator 检查。
```

## Graph Route

```text
plan_validator
-> route_after_plan_validation
-> repair
-> plan_repair
-> plan_validator
```

如果超过最大 repair 次数：

```text
plan_repair_limit_exceeded
-> fail
```

## 示例

坏 plan：

```text
list_all_candidates -> count_candidates
```

错误：

```text
semantic: filtered candidate scope cannot be produced by all-scope source list_all_candidates
```

修复：

```text
build_rule_plan
-> filter_candidates(domains_any=["金融"]) -> candidate_pool
-> count_candidates(candidate_pool)
-> refresh_artifact_bindings
-> plan_validator
```
