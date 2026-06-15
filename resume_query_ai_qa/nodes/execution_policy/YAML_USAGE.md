# Execution Policy YAML Usage

这份文档是 YAML 字段地图，不是执行流程。执行流程看 `EXECUTION_FLOW.md`。

## 直接使用

## compiler_templates.yaml

`execution_policy` 直接读取：

```yaml
workflows:
  <workflow_name>:
    priority: 100
    match:
      intent: compound
      intents: [...]
      required_sub_intents: [...]
      scenarios: [...]
      requires_scope: true
```

字段含义：

| 字段 | 谁使用 | 用途 |
|---|---|---|
| `workflows` | `match_workflow` | 候选稳定 workflow 集合。 |
| `priority` | `match_workflow` | 从高到低匹配，第一个命中生效。 |
| `match.intent` | `_workflow_matches` | 单个主 intent 必须相等。 |
| `match.intents` | `_workflow_matches` | 主 intent 必须在列表里。 |
| `match.required_sub_intents` | `_workflow_matches` | compound 必须包含这些子 intent。 |
| `match.scenarios` | `_workflow_matches` | 当前 scenarios 至少命中一个。 |
| `match.requires_scope` | `_workflow_matches` | 必须有明确范围条件或候选人池上下文。 |

`execution_policy` 不使用但后续节点使用：

| 字段 | 后续节点 | 用途 |
|---|---|---|
| `artifact_type` | `plan_compiler` / validator | template 产物类型。 |
| `tool_calls` | `plan_compiler` | 编译成 `QueryPlan` 工具调用。 |
| `sub_tasks` | `plan_compiler` | 复合 workflow 的子任务模板。 |
| `evidence` | `plan_compiler` | 证据检索时机和候选人数量。 |
| `notes` | `plan_compiler` / validator | trace 和 artifact contract 标记。 |
| `artifact_contracts` | validator | 检查工具入参引用是否符合模板合同。 |

## 间接使用

## scenarios.yaml

`execution_policy` 不直接解析 `scenarios.yaml` 的原始字段，而是通过 `ResumeQAConfig` 间接使用。

| 配置查询 | 来源 | 用途 |
|---|---|---|
| `planner_for_scenarios(...)` | `scenarios.yaml.scenarios.*.planner` | generic 路径选择 rule/LLM planner。 |
| `scenario_for_intent(...)` | `RouterOutput.scenario_decisions` | 读取 router/finalizer 已确定的 scenario。 |
| `resolve_scenario(...)` | `scenarios.yaml.resolution_rules` | rule fallback / benchmark 使用；主 policy 不重新判定 scenario。 |

注意：

- scenario 的权威来源是 router/finalizer 后的 `RouterOutput.scenario_decisions`。
- `execution_policy` 只读取 scenario，不重新判定 scenario。

## 环境开关

`config.compiler_flags()` 会读取项目 `.env` 或运行时环境：

| 变量 | 作用 |
|---|---|
| `RESUME_QA_WORKFLOW_TEMPLATE_COMPILER_ENABLED` | 是否启用 workflow template 能力；开启时走 hybrid，未配置或关闭时走 pure generic。 |

默认逻辑：

```text
RESUME_QA_WORKFLOW_TEMPLATE_COMPILER_ENABLED=true
-> hybrid_template_binding

未配置或 false
-> generic_tool_binding
```

## 与上游字段关系

`execution_policy` 的 workflow 匹配不是直接匹配用户原文，而是匹配上游结构化结果：

| workflow match | 上游字段 |
|---|---|
| `intent` / `intents` | `RouterOutput.intent` |
| `required_sub_intents` | `RouterOutput.sub_intent_candidates` |
| `scenarios` | `RouterOutput.scenario_decisions` |
| `requires_scope` | `RouterOutput.normalized_conditions` / `context_policy` |

所以如果 workflow 没命中，优先排查：

```text
router intent 是否正确
finalizer scenario 是否正确
condition_normalizer 是否生成 normalized_conditions
compiler_templates.yaml 的 match 是否过窄
compiler mode 是否强制 generic
```
