# Inspection Package

`core/inspection/` 是只读检查 helper 层。

一句话：

```text
inspection = QueryPlan / ToolResult / artifact binding 的只读结构检查
```

它给 compiler、validator、answer 侧提供统一读取方式，但不修 plan、不执行工具。

## 文件地图

| 文件 | 职责 |
| --- | --- |
| `plan_inspection.py` | 展开 plan tool calls、读取工具名、依赖和参数 |
| `plan_artifacts.py` | 生成/刷新 artifact binding，检查 canonical source |
| `result_inspection.py` | 从 ToolResult 中读取 count、candidate ids、evidence、ranking 等事实 |
| `__init__.py` | 包说明 |

## 主要联动

```text
plan_compiler
-> refresh_artifact_bindings
-> inspection.plan_artifacts
```

```text
plan_validator
-> inspection.plan_inspection / plan_artifacts
-> ValidationResult
```

```text
execution_validator / answer_validator
-> inspection.result_inspection
-> 检查工具结果事实
```

## 它不做什么

- 不修改 graph state。
- 不调用 tools。
- 不修复 plan。
- 不生成答案。
- 不判断自然语言 intent。

## 排查地图

| 问题 | 看哪里 |
| --- | --- |
| plan 里有哪些工具调用看不清 | `plan_inspection.py` |
| artifact binding / canonical source 错 | `plan_artifacts.py` |
| ToolResult count/ranking/evidence 读取错 | `result_inspection.py` |
