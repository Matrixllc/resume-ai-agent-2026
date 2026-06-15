# Plan Building Rules

`core/rules/plan_building/` 是 QueryPlan 构建规则层。

一句话：

```text
plan_building = SemanticPlan / RouterOutput / config / context -> ToolCallSpec / QueryPlan
```

它不决定用户 intent，也不执行工具。它只把已经确定的语义计划编译成可执行工具调用结构。

## 它做什么

- 根据 `tool_policy.yaml.tools.*.binding_kind` 生成工具调用。
- 从 `RouterOutput.conditions` / `normalized_conditions` 生成工具参数。
- 把 `$candidate_pool.resume_identity[]` 这类引用转成 structured refs。
- 处理 canonical candidate source，避免 count/rank/evidence 用到不同候选池。
- 复用上下文候选人或 JD criteria。
- 去重重复工具调用。

## 文件地图

| 文件 | 职责 |
| --- | --- |
| `builders.py` | 按 binding kind 构造具体 `ToolCallSpec` |
| `query_args.py` | 生成 filter args、ranking args、retrieval query |
| `refs.py` | `$ref` / structured ref 转换和 root 替换 |
| `source_policy.py` | canonical candidate source、source signature、source 冲突检查 |
| `orchestration.py` | sub-task、tool sequence、call normalize |
| `hints.py` | LLM planner tool hints 去重、评分、拒绝原因 |
| `__init__.py` | 兼容导出入口 |

## 主要联动

```text
nodes/plan_compiler
-> plan_building
-> QueryPlan
```

```text
nodes/plan_repair / execution_repair
-> plan_building
-> rebuilt / fallback QueryPlan
```

```text
nodes/plan_validator
-> inspection
-> 检查 plan_building 产物是否合法
```

## 参数怎么来

示例：

```text
domain condition: 金融
-> query_args.filter_args
-> {"domains_any": ["金融"]}
-> builders.generic_call_for_tool
-> ToolCallSpec.arguments
```

引用示例：

```text
filter_candidates output_key="candidate_pool"
-> score_candidates_for_jd(candidate_ids="$candidate_pool.resume_identity[]")
-> refs.with_structured_refs
-> structured ref
```

## 边界

不在这里做：

- router intent 判断
- LLM 规划
- plan validation
- tool execution
- answer generation

## 排查地图

| 问题 | 看哪里 |
| --- | --- |
| `domains_any` / `skills_any` 参数错 | `query_args.py` |
| `$ref` 绑定错 | `refs.py` |
| 同一个复合问题候选池不一致 | `source_policy.py` |
| 某个 tool call 没生成 | `builders.py`、`orchestration.py` |
| LLM hint 被拒绝 | `hints.py` |
