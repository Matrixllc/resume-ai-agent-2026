# Planner Flow

这份文档只讲代码阅读线。YAML 字段地图看 `YAML_USAGE.md`，节点总览看 `README.md`。

## 阅读入口

```text
planner.py
-> llm.py
-> rules.py
-> core/rules/semantic_plan.py
```

注意：`nodes/planner/rules.py` 只是兼容导出 wrapper。真正的 rule planner 在 `core/rules/semantic_plan.py`。

## 1. resolve_semantic_plan

位置：

```text
nodes/planner/planner.py
```

输入：

- `question`
- `router_output`
- `decision`
- `use_llm`
- `config`

输出：

- `SemanticPlan`
- trace meta

执行过程：

```text
decision.planner == rule
-> semantic_plan_from_router
-> meta.engine = rule

decision.planner == llm，但 use_llm/config 禁用
-> semantic_plan_from_router
-> meta.engine = rule

decision.planner == llm，且 LLM 可用
-> semantic_plan_llm
-> 成功：meta.engine = llm
-> 失败：meta.engine = rule_fallback
```

为什么这么做：

- `execution_policy` 决定是否需要 LLM planner。
- planner 只执行该决策，并保证 LLM 不可用时仍有确定性 rule fallback。

## 2. semantic_plan_from_router

位置：

```text
core/rules/semantic_plan.py
```

输入：

- `router_output`
- `decision`
- `config`

输出：

- `SemanticPlan`

执行过程：

```text
如果 router_output.intent == compound
-> intents = router_output.sub_intent_candidates

否则
-> intents = [router_output.intent]

每个 intent
-> semantic_step_from_config

最后组装 SemanticPlan
```

生成字段：

```text
intent = router_output.intent
is_compound = router_output.intent == compound
steps = SemanticStep[]
context_policy = router_output.context_policy
normalized_conditions = router_output.normalized_conditions
compile_strategy = domain_template
notes = ["semantic_plan_from_router", "yaml_driven_rule_planner"]
```

## 3. semantic_step_from_config

位置：

```text
core/rules/semantic_plan.py
```

职责：

```text
为单个 intent 生成一个 SemanticStep。
```

读取：

```text
scenario_for_intent(router_output, intent)
config.semantic_needs_for_intent(intent)
config.semantic_defaults_for_intent(intent, scenario)
config.preferred_tool_hints_for_scenario(intent, scenario)
router_output.normalized_conditions
router_output.sub_intent_evidence
```

输出字段：

| 字段 | 来源 |
|---|---|
| `intent` | 当前 intent |
| `scenario` | `router_output.scenario_decisions` |
| `needs` | `intents.yaml.semantic_needs` |
| `tool_hints` | `tool_policy.yaml` |
| `tool_hint_scores` | `tool_policy.yaml` 转成 `ToolHint` |
| `conditions` | `router_output.normalized_conditions` |
| `requires_jd` | router flag 或 intent/scenario defaults |
| `requires_evidence` | router flag 或 intent/scenario defaults |
| `evidence` | `router_output.sub_intent_evidence` |
| `reason` | `derived_from_router_and_yaml` |

## 4. semantic_plan_llm

位置：

```text
nodes/planner/llm.py
```

职责：

```text
让 LLM 产出 SemanticPlan draft，然后交给 normalize_semantic_plan 收口。
```

执行过程：

```text
_planner_prompt_context
-> build_semantic_planner_prompt
-> invoke_structured(SemanticPlan)
-> normalize_semantic_plan
-> 成功返回 SemanticPlan

任何异常
-> semantic_plan_from_router
-> 返回 fallback_reason
```

注意：

- LLM draft 不是最终权威。
- LLM 不能越权改 router/finalizer 已经确定的 intent、conditions、context。

## 5. _planner_prompt_context

位置：

```text
nodes/planner/llm.py
```

输入：

- `router_output`
- `decision`
- `config`

输出给 prompt：

```text
scenarios_by_intent
tool_capabilities_by_intent
semantic_needs_by_intent
```

为什么这么做：

- LLM 只看到允许范围内的 scenario、tool capabilities、semantic needs。
- prompt 不让 LLM 自己发明工具合同。

## 6. normalize_semantic_plan

位置：

```text
core/rules/semantic_plan.py
```

职责：

```text
把 LLM draft 拉回 RouterOutput + YAML 权威边界。
```

收口规则：

```text
intent / is_compound
-> 以 router_output 为准

steps
-> 必须按 router_output intent/sub_intents 重建

conditions
-> 以 router_output.normalized_conditions 为准

context_policy
-> 以 router_output.context_policy 为准

tool hints
-> YAML configured hints + LLM hints 合并去重

needs
-> YAML required needs + LLM 允许的 optional needs

requires_jd / requires_evidence
-> YAML/router true 不能被 LLM 改 false；LLM 可以补 true
```

## 7. _meta

位置：

```text
nodes/planner/planner.py
```

输出 trace meta：

```text
node = planner
engine = rule / llm / rule_fallback
fallback_reason = ...
llm = llm identity
```

## 8. _short_error

位置：

```text
nodes/planner/llm.py
```

职责：

```text
把 LLM 异常压缩成 300 字符以内的 fallback_reason。
```

## 示例

问题：

```text
找找可能和金融风控相关的人
```

上游可能产出：

```text
RouterOutput.intent = candidate_filter
scenario = open_recall
normalized_conditions = [concept/domain: 金融风控]
ExecutionDecision.compiler = generic_tool_binding
ExecutionDecision.planner = llm 或 rule
```

rule planner 生成：

```text
SemanticPlan.intent = candidate_filter
SemanticPlan.is_compound = false
SemanticPlan.steps[0].intent = candidate_filter
SemanticPlan.steps[0].scenario = open_recall
SemanticPlan.steps[0].conditions = 金融风控 normalized_conditions
SemanticPlan.steps[0].needs = intents.yaml.semantic_needs
SemanticPlan.steps[0].tool_hints = tool_policy.yaml 推荐工具
```

之后：

```text
SemanticPlan
-> plan_compiler
-> QueryPlan
```
