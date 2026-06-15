# Config Package

`core/config/` 是 Query-AI 的配置加载与查询 facade。

一句话：

```text
core/config = 读取 configs/*.yaml，构造 ResumeQAConfig，并给 nodes 提供稳定查询方法
```

这里不做业务节点决策。它只负责把 YAML 变成可安全消费的配置对象。

## 架构位置

```text
graph.run / benchmark / scripts
-> load_config()
-> load_yaml(...)
-> ResumeQAConfig
-> validate_config_structure(...)
-> load_project_env(...)
-> nodes / core rules / validators
```

## 它做什么

- 统一加载 `resume_query_ai_qa/configs/*.yaml`。
- 构造 `ResumeQAConfig`。
- 调用 `core/config_validation` 做启动期结构校验。
- 加载项目 `.env` 中的 compiler flags。
- 给节点提供查询方法，例如：
  ```text
  allowed_tools_for_intent
  allowed_scenarios_for_intent
  semantic_defaults_for_intent
  default_output_key
  tool_produces
  retry_limit
  answer_layout_rules
  ```

## 它不做什么

- 不判断用户 intent。
- 不选择 workflow。
- 不生成 tool call。
- 不执行工具。
- 不修复配置。
- 不回答用户问题。

## 文件职责

| 文件 | 职责 | 阅读入口 |
| --- | --- | --- |
| `loader.py` | YAML 加载入口，构造 config 并触发校验 | `load_config` |
| `model.py` | `ResumeQAConfig` 和所有配置查询方法 | `ResumeQAConfig` |
| `compiler_flags.py` | `.env` compiler mode 开关解析 | `compiler_flags_for_config` |
| `tool_hints.py` | 归一化 LLM planner tool hints | `normalize_tool_hints` |
| `__init__.py` | 稳定导出入口 | `load_config`, `ResumeQAConfig` |

## 核心原则

Node 不应该到处直接读 raw YAML。

推荐：

```python
config.allowed_tools_for_intent(intent, scenario)
config.default_output_key(tool_name)
config.retry_limit("plan_repair", 0)
```

不推荐：

```python
config.tool_policy["intent_tools"][intent]["scenarios"][scenario]
```

原因：

- YAML shape 变化时只改 facade。
- planner/compiler/validator 能共享同一套解释。
- 启动期校验能覆盖更多引用错误。

## 和 configs 的边界

`configs/` 是规则真源。

`core/config/` 是读取和查询层：

```text
YAML shape
-> ResumeQAConfig fields
-> query methods
-> node consumption
```

## 和 config_validation 的边界

`core/config/loader.py` 调用：

```text
validate_config_structure(cfg)
```

校验失败时直接抛错，不让坏配置进入运行时。

`core/config/` 不负责修复，也不吞掉配置错误。

## 阅读顺序

1. [README.md](README.md)
2. [CONFIG_FLOW.md](CONFIG_FLOW.md)
3. [loader.py](loader.py)
4. [model.py](model.py)
5. [compiler_flags.py](compiler_flags.py)
6. [../config_validation/README.md](../config_validation/README.md)
7. [../../configs/README.md](../../configs/README.md)

## 是否需要优化架构

当前不建议拆 `model.py`。

理由：

- `ResumeQAConfig` 是有意设计的统一 facade。
- 方法虽然多，但都是“查询配置”，职责一致。
- 拆成多个 mixin 会增加跳转，对当前规模收益不高。
- 更重要的是约束 nodes 通过 facade 读配置，而不是各自展开 YAML。

## 验收

```bash
rg "Config Package|CONFIG_FLOW|load_config|ResumeQAConfig|allowed_tools_for_intent" resume_query_ai_qa/core/config
./.venv/bin/python -m compileall -q resume_query_ai_qa/core/config
./.venv/bin/python -c "from resume_query_ai_qa.core.config import load_config; cfg = load_config(); print(len(cfg.intents.get('intents', {})))"
```
