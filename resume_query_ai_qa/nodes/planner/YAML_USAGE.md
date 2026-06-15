# Planner YAML Usage

这份文档是 YAML 字段地图，不是执行流程。执行流程看 `PLANNER_FLOW.md`。

## 直接 / 间接使用的 YAML

planner 主要通过 `ResumeQAConfig` 查询这些配置：

```text
intents.yaml
tool_policy.yaml
scenarios.yaml
```

## intents.yaml

### semantic_needs

读取方式：

```text
config.semantic_needs_for_intent(intent)
```

使用位置：

```text
semantic_step_from_config
```

作用：

```text
生成 SemanticStep.needs。
```

含义：

```text
这个 intent 语义上需要哪些信息。
```

例如：

```yaml
semantic_needs:
  - resolve_candidate
  - profile
  - evidence
```

这些不是工具调用，只是语义需求标签。后续 `plan_compiler` 会结合 tool policy 选择具体工具。

## scenario_optional_needs

读取方式：

```text
config.optional_semantic_needs_for_intent(intent, scenario)
```

使用位置：

```text
normalize_semantic_plan
```

作用：

```text
LLM draft 只能额外保留当前 scenario 允许的 optional needs。
```

为什么这么做：

- YAML required needs 是基础。
- LLM 可以补充，但不能无限发明 needs。

## scenario_defaults / requires flags

读取方式：

```text
config.semantic_defaults_for_intent(intent, scenario)
```

使用位置：

```text
semantic_step_from_config
```

作用：

```text
生成 SemanticStep.requires_jd
生成 SemanticStep.requires_evidence
```

合并规则：

```text
SemanticStep.requires_jd =
  router_output.requires_jd OR scenario/intents 默认值

SemanticStep.requires_evidence =
  router_output.requires_evidence OR scenario/intents 默认值
```

注意：

- router finalizer 已经做过权威收口。
- planner 这里再对齐 YAML defaults，是为了让 SemanticStep 自身字段完整。

## tool_policy.yaml

### intent_tools

读取方式：

```text
config.preferred_tool_hints_for_scenario(intent, scenario)
config.tool_capabilities_for_intent(intent, scenario)
```

使用位置：

```text
semantic_step_from_config
_planner_prompt_context
```

作用：

```text
生成 tool_hints / tool_hint_scores。
给 LLM prompt 暴露允许的工具能力。
```

常见字段：

```yaml
intent_tools:
  candidate_filter:
    preferred_tools: [...]
    preferred_tool_hints: [...]
    scenarios:
      open_recall:
        preferred_tools: [...]
        preferred_tool_hints: [...]
```

planner 只使用这些字段做工具建议。

重要边界：

```text
tool_hints 不是 ToolCallSpec。
tool_hints 没有 arguments / depends_on / output_key / $ref。
最终工具调用由 plan_compiler 生成。
```

## tools metadata

读取方式：

```text
config.tool_capabilities_for_intent(intent, scenario)
```

使用位置：

```text
_planner_prompt_context
```

作用：

```text
给 LLM prompt 提供工具名和 description。
```

planner 不读取工具的底层执行实现，也不调用工具。

## scenarios.yaml

### scenarios.*.planner

读取方式：

```text
config.planner_for_scenarios(scenarios)
```

主要使用位置：

```text
execution_policy
```

对 planner 的影响：

```text
ExecutionDecision.planner = rule / llm
```

planner 本身只执行这个 decision，不重新判定 scenario。

## scenario_decisions

planner 的 scenario 权威来源不是 YAML 原文，而是：

```text
RouterOutput.scenario_decisions
```

读取方式：

```text
scenario_for_intent(router_output, intent)
```

使用位置：

```text
semantic_step_from_config
```

## YAML 与输出字段对应表

| SemanticPlan / SemanticStep 字段 | 主要来源 |
|---|---|
| `SemanticPlan.intent` | `RouterOutput.intent` |
| `SemanticPlan.is_compound` | `RouterOutput.intent == compound` |
| `SemanticPlan.steps` | `RouterOutput.intent/sub_intent_candidates` |
| `SemanticPlan.context_policy` | `RouterOutput.context_policy` |
| `SemanticPlan.normalized_conditions` | `RouterOutput.normalized_conditions` |
| `SemanticStep.scenario` | `RouterOutput.scenario_decisions` |
| `SemanticStep.needs` | `intents.yaml.semantic_needs` |
| `SemanticStep.tool_hints` | `tool_policy.yaml.intent_tools` |
| `SemanticStep.tool_hint_scores` | `tool_policy.yaml.intent_tools` |
| `SemanticStep.requires_jd` | `RouterOutput.requires_jd` + `intents.yaml` defaults |
| `SemanticStep.requires_evidence` | `RouterOutput.requires_evidence` + `intents.yaml` defaults |
| `SemanticStep.evidence` | `RouterOutput.sub_intent_evidence` |

## 排查顺序

如果 planner 产出的 SemanticPlan 不符合预期，按这个顺序排查：

```text
1. execution_policy 是否真的走 generic 路径
2. ExecutionDecision.planner 是 rule 还是 llm
3. RouterOutput intent/sub_intents 是否正确
4. RouterOutput.scenario_decisions 是否正确
5. condition_normalizer 是否生成 normalized_conditions
6. intents.yaml semantic_needs/defaults 是否正确
7. tool_policy.yaml preferred tools/hints 是否正确
8. LLM draft 是否被 normalize_semantic_plan 收口
```
