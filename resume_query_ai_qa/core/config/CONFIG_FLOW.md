# Config Flow

这份文档按代码阅读顺序讲配置如何从 YAML 进入运行时。

## 1. 总链路

```text
graph.run / benchmark / script
-> load_config()
-> load_yaml(...)
-> ResumeQAConfig(...)
-> validate_config_structure(cfg)
-> load_project_env(cfg)
-> return cfg
```

所有 graph state 里的 `config` 都应该来自这里。

## 2. load_config

入口：

```text
load_config(configs_dir: Path | None = None)
```

执行过程：

```text
app_root = resume_query_ai_qa/
config_dir = configs_dir or app_root / "configs"
taxonomy_dir = app_root.parent / "shared_taxonomy"
```

然后逐个读取：

```text
intents.yaml
scenarios.yaml
tool_policy.yaml
jd_scoring.yaml
evidence_policy.yaml
validation.yaml
llm.yaml
router_rules.yaml
compiler_templates.yaml
answer_layouts.yaml
aggregator_tasks.yaml
condition_rules.yaml
```

最后：

```text
validate_config_structure(cfg)
load_project_env(cfg)
return cfg
```

## 3. load_yaml

入口：

```text
load_yaml(path)
```

职责：

- 文件不存在：抛 `FileNotFoundError`。
- YAML 为空：返回 `{}`。
- 顶层不是 mapping：抛 `ValueError`。
- 顶层是 mapping：返回 dict。

它不理解具体业务字段。

## 4. ResumeQAConfig

`ResumeQAConfig` 保存所有 YAML 原始 dict：

```text
intents
scenarios
tool_policy
jd_scoring
evidence_policy
validation
llm
router_rules
compiler_templates
answer_layouts
aggregator_tasks
condition_rules
```

并提供查询方法，避免 node 到处展开 YAML shape。

常见读取线：

```text
router finalizer
-> semantic_defaults_for_intent
-> intents.yaml
```

```text
planner/compiler/validator
-> allowed_tools_for_intent
-> tool_policy.yaml
```

```text
plan_compiler / inspection
-> default_output_key / tool_produces / tool_binding_kind
-> tool_policy.yaml.tools
```

```text
validators / repair
-> retry_limit
-> validation.yaml.retry_limits
```

```text
aggregator / answer_validator
-> answer_layout_rules / aggregator_task_rules
-> answer_layouts.yaml / aggregator_tasks.yaml
```

## 5. compiler_flags

入口：

```text
compiler_flags_for_config(config)
```

来源：

```text
.env
RESUME_QA_WORKFLOW_TEMPLATE_COMPILER_ENABLED
```

推导规则：

```text
RESUME_QA_WORKFLOW_TEMPLATE_COMPILER_ENABLED=true
-> hybrid_template_binding

未配置或 false
-> generic_tool_binding
```

输出：

```text
mode
workflow_template_enabled
generic_tool_binding_enabled
```

运行配置只暴露 workflow 开关；generic 作为基础路径始终可用。

## 6. 运行时消费方式

推荐：

```text
node receives config
-> config query method
-> node decision
```

不要让 node 私有维护 YAML 解释规则。

如果一个字段被多个节点使用，应优先加到 `ResumeQAConfig` 查询方法，而不是在每个节点复制展开逻辑。

## 7. 排查怎么读

配置文件缺失：

```text
loader.py -> load_yaml
```

YAML 引用未知 intent/tool/scenario：

```text
config_validation/
```

工具 allowed/preferred 不符合预期：

```text
model.py -> allowed_tools_for_intent / preferred_tools_for_scenario
tool_policy.yaml
```

compiler mode 不符合预期：

```text
compiler_flags.py
.env
```

answer layout 不符合预期：

```text
model.py -> answer_layout_rules
answer_layouts.yaml
```
