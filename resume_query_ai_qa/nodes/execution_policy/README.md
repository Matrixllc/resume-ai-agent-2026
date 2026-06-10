# Execution Policy Node

## 职责

`execution_policy` 是执行路径调度层。它读取 question 和标准化后的 `RouterOutput`，
产出 `ExecutionDecision`，决定本轮走 `workflow_template` 还是
`generic_tool_binding`。Scenario 的 canonical 来源是 `RouterOutput.scenario_decisions`；
本节点只读取和透传，不重新判定。

## 输入

| 输入 | 来源 | 用途 |
|---|---|---|
| `question` | 用户请求 | trace reason 和 workflow 匹配上下文。 |
| `RouterOutput.intent` | router | 确定需要调度的 intent。 |
| `sub_intent_candidates` | router | compound 中逐子 intent 调度。 |
| `scenario_decisions` | router | 读取每个 intent 的执行协议。 |
| `normalized_conditions` | condition normalizer | workflow scope 匹配。 |
| compiler templates | YAML | 判断是否命中稳定 workflow。 |

## 输出

| 输出 | 用途 |
|---|---|
| `ExecutionDecision.compiler` | graph 条件路由到 planner 或 plan_compiler。 |
| `ExecutionDecision.planner` | generic 路径使用 rule/LLM planner。 |
| `ExecutionDecision.workflow_name` | template 路径命中的 workflow。 |
| `ExecutionDecision.scenarios` | compiler/validator 使用的执行协议。 |
| `ExecutionDecision.reason` | trace 和 diagnosis 使用。 |

## 主流程

```text
question + normalized RouterOutput
-> read RouterOutput.scenario_decisions
-> match_workflow(...)
-> ExecutionDecision
-> graph route: template 或 generic
```

## 失败 / Fallback

`execution_policy` 本身不 repair。没有 workflow 命中时不是错误，会走 generic。

| 场景 | 行为 | Trace 字段 |
|---|---|---|
| workflow 命中 | route 到 `plan_compiler` | `route_events.reason=matched stable workflow:*` |
| workflow 未命中 | route 到 `planner` | `route_events.reason=no stable workflow matched` |
| open recall | `scenario=open_recall` | `ExecutionDecision.scenarios` |
| hard filter | `scenario=hard_filter` | validator 会保持严格 source contract |

## Trace 字段

- `execution_decision.compiler`
- `execution_decision.workflow_name`
- `execution_decision.scenarios`
- `decision_steps[].summary=compiler=...`
- `route_events[]`

## 边界：能做 / 不能做

能做：

- 读取并透传 router-owned scenario。
- 判断 template/generic。
- 给 graph 返回 route 标签。

不能做：

- 不生成 `SemanticPlan` 或 `QueryPlan`。
- 不重新判定 scenario。
- 不拼工具参数。
- 不调用 tools。
- 不修复 plan。

## 扩展方式

- 新稳定 workflow：更新 `compiler_templates.yaml`。
- 新 scenario：更新 router/finalizer 规则、`scenarios.yaml`、tool policy 和 validator。
- 新 open recall 词：更新 `router_rules.yaml`，代码只读配置。

## 验收 benchmark

```bash
.venv/bin/python resume_query_ai_qa/benchmarks/run_plan_contract_benchmark.py
.venv/bin/python resume_query_ai_qa/benchmarks/run_plan_contract_benchmark.py
```
