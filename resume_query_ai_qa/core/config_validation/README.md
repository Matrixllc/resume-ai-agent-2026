# Config Validation Package

`core/config_validation/` 是 Query-AI 的启动期配置合同检查层。

一句话：

```text
config_validation = 在运行 graph 前检查 YAML 之间的引用是否合法
```

它不执行业务逻辑，也不修复配置；发现错误就让 `load_config()` 失败。

## 架构位置

```text
load_config()
-> ResumeQAConfig
-> validate_config_structure(config)
-> validate_scenarios / validate_tool_policy / validate_templates / ...
-> ConfigStructureError or OK
```

## 它做什么

- 检查 scenario 是否引用合法 intent。
- 检查 router rule 是否引用合法 intent / signal group。
- 检查 tool policy 是否引用合法 tool / scenario / intent。
- 检查 compiler template 的 workflow、tool call、binding 是否合法。
- 检查 answer layout / aggregator task 是否引用合法工具。
- 检查 condition rules / validation rules 的基本结构。
- 检查 shared taxonomy 结构。

## 它不做什么

- 不运行 router/planner/compiler。
- 不判断用户 query。
- 不生成 `QueryPlan`。
- 不调用 tools。
- 不修复 YAML。
- 不做运行时 fallback。

## 文件职责

| 文件 | 职责 |
| --- | --- |
| `orchestrator.py` | 总入口，编排所有校验并抛 `ConfigStructureError` |
| `scenarios.py` | 校验 scenario、resolution_rules、router_rules 引用 |
| `tool_policy.py` | 校验 intent_tools、tool metadata、fallback_tool、result requirements |
| `compiler_templates.py` | 校验 workflow、tool_calls、sub_tasks、`$binding` |
| `answer_rules.py` | 校验 answer_layouts 和 aggregator_tasks 的工具引用 |
| `condition_validation.py` | 校验 condition_rules 和 validation.yaml 基本结构 |
| `taxonomy_validation.py` | 校验 shared_taxonomy 文件结构 |
| `common.py` | 校验 helper |
| `__init__.py` | 稳定导出入口 |

## 校验失败长什么样

`validate_config_structure()` 收集所有错误后一次性抛：

```text
ConfigStructureError(
  "Invalid QA config structure:
  - tool_policy.yaml: ...
  - compiler_templates.yaml: ..."
)
```

这样可以一次修多处配置，而不是每次启动只暴露一个错误。

## 和 runtime validator 的区别

`config_validation`：

- 启动期运行。
- 检查 YAML 是否自洽。
- 输入是 config。
- 输出是 OK 或异常。

`plan_validator` / `execution_validator` / `answer_validator`：

- 运行时运行。
- 检查某一轮 query 的 plan/result/answer 是否满足合同。
- 输入是 `QueryPlan` / `ToolResult[]` / `AggregatedAnswer`。
- 输出是 `ValidationResult`。

## 是否需要优化架构

当前不建议大拆。

理由：

- 已经按 YAML 领域拆分。
- `orchestrator.py` 作为单一入口很清楚。
- validator 函数都比较小，继续保持“收集 errors list”模式即可。

可做的阅读性优化：

- 保留现有文件结构。
- 补 README / FLOW。
- 少量清理 docstring。

## 阅读顺序

1. [README.md](README.md)
2. [VALIDATION_FLOW.md](VALIDATION_FLOW.md)
3. [orchestrator.py](orchestrator.py)
4. [scenarios.py](scenarios.py)
5. [tool_policy.py](tool_policy.py)
6. [compiler_templates.py](compiler_templates.py)
7. [answer_rules.py](answer_rules.py)
8. [condition_validation.py](condition_validation.py)
9. [taxonomy_validation.py](taxonomy_validation.py)

## 验收

```bash
rg "Config Validation Package|VALIDATION_FLOW|validate_config_structure|ConfigStructureError" resume_query_ai_qa/core/config_validation
./.venv/bin/python -m compileall -q resume_query_ai_qa/core/config_validation
./.venv/bin/python -c "from resume_query_ai_qa.core.config import load_config; load_config(); print('OK: config validation')"
```
