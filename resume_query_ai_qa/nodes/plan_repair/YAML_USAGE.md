# Plan Repair YAML Usage

这份文档是 YAML 字段地图，不是执行流程。执行流程看 `PLAN_REPAIR_FLOW.md`。

## validation.yaml

## issue_actions

使用位置：

```text
classify_plan_repair_action
validation_action(...)
```

作用：

```text
把 plan_validator 的错误分类成 repair / clarify / fail。
```

例子：

```yaml
issue_actions:
  codes:
    context_missing:
      action: clarify
    dependency_contract:
      action: repair
    argument_binding:
      action: fail
```

在 `plan_repair` 里：

```text
action=repair
-> action=rule_repair
```

## legacy_issue_classifiers

使用位置：

```text
validation_issues(errors, "plan")
```

作用：

```text
把错误字符串转成结构化 ValidationIssue。
```

例子：

```yaml
- code: dependency_contract
  contains_any: [depends_on unknown, argument references unknown]
```

如果 validator error 包含：

```text
depends_on unknown
```

就会分类为：

```text
dependency_contract
```

## plan_repair.llm_enabled

使用位置：

```text
repair_plan
```

配置：

```yaml
plan_repair:
  llm_enabled: false
```

含义：

```text
默认禁用 LLM plan repair。
```

即使打开，也只有 semantic 错误、LLM 可用、且不属于 deterministic intent 时才会尝试。

## retry_limits / graph repair 次数

`validation.yaml.retry_limits` 是全局重试配置的一部分。graph state 里还会保存：

```text
max_plan_repairs
plan_repairs
```

route 逻辑：

```text
如果 plan_repairs < max_plan_repairs
-> plan_repair

否则
-> fail: plan_repair_limit_exceeded
```

## tool_policy.yaml

LLM repair prompt 会读取：

```text
config.allowed_tools_for_intent(intent, scenario)
config.forbidden_tools_for_scenario(intent, scenario)
```

用途：

```text
给 LLM 暴露每个 intent 可以使用的工具集合。
```

注意：

```text
rule repair 不直接依赖这里做分类，
但 build_rule_plan -> sub_task_for_intent 会通过 plan_building/config 使用 tool policy。
```

## RouterOutput.scenario_decisions

严格说它不是 YAML，但它来自 router/finalizer 对 `scenarios.yaml` 的收口。

使用位置：

```text
allowed_tools_by_intent
sub_task_for_intent
```

作用：

```text
决定某 intent 当前 scenario 下允许哪些工具。
```

## tool registry

严格说它不是 YAML，但 LLM repair 会读取：

```text
get_tool_registry()
```

使用位置：

```text
tool_specs()
```

作用：

```text
把工具函数参数名提供给 LLM repair prompt。
```

最终安全性仍由 `plan_validator` 复检保证。

## 输出字段来源表

| repair_plan 返回项 | 来源 |
|---|---|
| `QueryPlan` | `build_rule_plan` / `repair_llm_plan` / previous_plan。 |
| `decision.action` | `validation.yaml.issue_actions`。 |
| `decision.category` | `validation_issues` 分类结果。 |
| `decision.reason` | `validation.yaml.issue_actions` 或 fallback reason。 |
| `engine` | `rule` / `llm` / `rule_fallback`。 |
| `fallback_reason` | LLM 失败或空字符串。 |

## 排查顺序

如果 plan repair 结果不符合预期，按这个顺序看：

```text
1. plan_validator error 被分类成什么 ValidationIssue
2. validation.yaml issue_actions 是否把它设成 repair / clarify / fail
3. 是否超过 max_plan_repairs
4. router_output intent/conditions/context 是否正确
5. build_rule_plan 是否按 router_output 重建了正确 QueryPlan
6. refresh_artifact_bindings 是否重新生成产物绑定
7. repaired plan 是否再次被 plan_validator 拦截
8. LLM repair 是否被显式启用，且是否属于 deterministic intent
```
