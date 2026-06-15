# Config Validation Flow

这份文档按执行顺序讲启动期配置校验。

## 1. 总入口

```text
load_config
-> validate_config_structure(config)
```

`validate_config_structure()` 不立即抛第一个错误，而是收集所有错误，最后统一抛 `ConfigStructureError`。

## 2. 预计算集合

入口：

```text
validate_config_structure(config)
```

先提取：

```text
intents = intents.yaml.intents keys
scenarios = scenarios.yaml.scenarios keys
tools = tool_policy.yaml.tools keys
allowed_pairs = scenario_pairs(scenarios.yaml)
```

这些集合供后续跨文件引用校验复用。

## 3. scenarios 校验

执行：

```text
validate_scenarios(config.scenarios, intents, errors)
```

检查：

- scenario 的 `planner` 必须是 `rule` 或 `llm`。
- scenario 必须声明 `allowed_intents`。
- `allowed_intents` 必须存在于 `intents.yaml`。
- routable intent 必须有 `resolution_rules`。
- resolution rule 只能使用支持的条件 key。
- resolution rule 指向的 scenario 必须允许该 intent。

然后：

```text
validate_router_rules(config.router_rules, intents, errors)
```

检查 router context resolution 只引用合法 intent、context ref type 和 signal group。

## 4. tool_policy 校验

执行：

```text
validate_intent_tools(...)
validate_tool_metadata(...)
```

检查：

- `intent_tools` 引用的 intent 必须存在。
- scenario 级工具策略引用的 scenario 必须存在。
- intent/scenario 组合必须被 `scenarios.yaml` 允许。
- allowed/preferred/forbidden 工具必须存在于 `tool_policy.yaml.tools`。
- tool metadata 必须声明 `produces`、`default_output_key`、`binding_kind`。
- `fallback_tool` 必须引用已知工具。
- `intent_result_requirements` 和 `business_limits` 引用合法工具。

## 5. compiler_templates 校验

执行：

```text
validate_compiler_templates(...)
```

检查：

- workflow match 引用合法 intent。
- workflow match 引用合法 scenario。
- scenario 与 intent 组合必须被 `scenarios.yaml` 允许。
- tool_calls 引用合法工具。
- sub_task intent 合法。
- `$binding` 只使用支持项：
  ```text
  filter_args
  ranking_criteria_tool
  retrieval_query
  workflow_evidence_max_candidates
  ```

## 6. answer / aggregator 校验

执行：

```text
validate_answer_layouts(config.answer_layouts, tools, errors)
validate_aggregator_tasks(config.aggregator_tasks, tools, errors)
```

检查：

- answer layout required tools 是否存在。
- aggregator task required tools 是否存在。
- layout/task 基本结构是否满足运行时消费需要。

## 7. condition / validation 校验

执行：

```text
validate_condition_rules(config.condition_rules, errors)
validate_validation_rules(config.validation, errors)
```

检查：

- condition extraction / taxonomy alias / preference target 的基本结构。
- validation issue action、retry limit、answer/privacy 等结构。

这类校验偏结构，不做自然语言规则是否“合理”的判断。

## 8. taxonomy 校验

执行：

```text
validate_taxonomy(config.taxonomy_dir, errors)
```

检查 `shared_taxonomy/` 中 domain/skill/concept/major 等 taxonomy 文件结构，避免 condition normalizer 运行时才发现 taxonomy 不可读。

## 9. 错误收口

如果 `errors` 非空：

```text
raise ConfigStructureError("Invalid QA config structure:\n- ...")
```

如果为空：

```text
return None
```

## 10. 排查怎么读

intent / scenario 引用错：

```text
scenarios.py
intents.yaml
scenarios.yaml
```

工具名引用错：

```text
tool_policy.py
tool_policy.yaml
tools/registry.py
```

workflow binding 错：

```text
compiler_templates.py
compiler_templates.yaml
```

answer layout 工具要求错：

```text
answer_rules.py
answer_layouts.yaml
aggregator_tasks.yaml
```

condition/taxonomy 错：

```text
condition_validation.py
taxonomy_validation.py
condition_rules.yaml
shared_taxonomy/
```
