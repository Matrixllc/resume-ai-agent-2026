# Plan Validator YAML Usage

这份文档是 YAML 字段地图，不是执行流程。执行流程看 `PLAN_VALIDATOR_FLOW.md`。

## tool_policy.yaml

## intent_tools

使用位置：

```text
plan_structure.py
```

读取方式：

```text
config.allowed_tools_for_intent(intent, scenario)
config.forbidden_tools_for_scenario(intent, scenario)
```

用途：

```text
校验每个 intent/scenario 下工具是否允许。
```

例子：

```text
hard_filter 下 candidate_filter 禁止 hybrid_search_candidates
open_recall 下 candidate_filter 允许 hybrid_search_candidates
```

## tools metadata

使用位置：

```text
plan_artifacts.py
plan_semantics.py
```

常用字段：

| 字段 | 用途 |
|---|---|
| `roles` | 找 candidate_source、criteria_source、evidence_capable 工具。 |
| `produces` | artifact binding / debug 使用。 |
| `scope` | candidate source scope 判断。 |
| `bind_primary_artifact` | 是否参与 canonical artifact binding。 |

validator 通过这些字段判断：

```text
哪些工具能产出候选人集合
哪些工具能产出评分标准
哪些工具能产出证据
```

## scenarios.yaml

使用位置：

```text
plan_structure.py -> validate_router_scenario_contract
```

读取方式：

```text
config.scenario_names()
config.allowed_scenarios_for_intent(intent)
```

用途：

```text
校验 RouterOutput.scenario_decisions 是否合法。
```

检查：

```text
scenario 名称存在
scenario 允许对应 intent
compound 每个 sub_intent 都有 scenario
没有无关 intent 的 scenario decision
```

## compiler_templates.yaml

## artifact_contracts

使用位置：

```text
plan_artifacts.py
```

用途：

```text
校验 workflow 编译出来的工具参数引用是否符合模板合同。
```

例子：

```yaml
artifact_contracts:
  - tool: count_candidates
    argument: candidates
    expected_ref: canonical_candidate_collection
```

含义：

```text
count_candidates.candidates 必须消费 canonical candidate_collection。
```

`canonical_candidate_collection` 会在运行时替换成实际 canonical root，例如：

```text
candidate_pool
```

## validation.yaml

## compare_pair

使用位置：

```text
plan_boundaries.py -> validate_compare_boundaries
```

字段：

```yaml
compare_pair:
  exact_candidate_count: 2
```

用途：

```text
candidate_compare_pair 必须刚好两个候选人。
```

## ranking

使用位置：

```text
plan_boundaries.py -> validate_ranking_boundaries
```

字段：

```yaml
ranking:
  requires_jd_criteria: true
  default_jd_tool: load_default_jd_criteria
```

用途：

```text
candidate_ranking 必须有 criteria source、score、rank。
```

## issue_actions / legacy_issue_classifiers

使用位置：

```text
validate_plan -> validation_issues(errors, "plan")
graph route / behavior contract
```

用途：

```text
把错误字符串分类成结构化 ValidationIssue，
再决定后续是 repair、clarify 还是 fail。
```

例子：

```text
contains: depends_on unknown
-> code=dependency_contract
-> action=repair
```

```text
contains: missing required context
-> code=context_missing
-> action=clarify
```

## tool registry

严格说它不是 YAML，但 validator 会直接使用：

```text
get_tool_registry()
```

用途：

```text
检查工具名是否存在
检查 ToolCallSpec.arguments 是否符合真实函数签名
```

如果工具函数没有 `**kwargs`，validator 会拒绝未知参数。

## 输出字段来源表

| ValidationResult 字段 | 来源 |
|---|---|
| `ok` | 是否有 errors。 |
| `errors` | 各检查函数返回的错误列表。 |
| `warnings` | 当前通常为空，保留扩展。 |
| `error_details` | `validation_issues(errors, "plan")`。 |
| `repair_hint` | `validate_plan` 固定提示。 |
| `next_node` | 通过为 `executor`，失败默认为 `plan_repair`。 |

## 排查顺序

如果 plan_validator 拦截计划，按这个顺序看：

```text
1. 错误是否来自 tool policy：allowed/forbidden tools
2. 错误是否来自工具签名：unsupported/missing arguments
3. 错误是否来自 depends_on/$ref
4. 错误是否来自 count/ranking/compare 边界
5. 错误是否来自 canonical candidate source
6. 错误是否来自 RouterOutput normalized_conditions 未进入 plan
7. 错误是否来自 context 缺失
8. 错误是否来自 requires_evidence 但没有证据工具
```
