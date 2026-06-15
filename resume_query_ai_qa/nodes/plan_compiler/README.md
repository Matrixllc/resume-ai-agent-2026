# Plan Compiler Node

一句话：`plan_compiler` 把 `SemanticPlan + RouterOutput + ExecutionDecision` 编译成 executor 可以执行的 `QueryPlan`。

## 架构位置

```text
user question
-> router
-> condition_normalizer
-> execution_policy
   -> template: plan_compiler
   -> generic: planner -> plan_compiler
-> plan_validator
-> executor
-> aggregator / answer_rewrite
```

`plan_compiler` 是第一层允许创建 `ToolCallSpec` 的节点。它不执行工具，只把上游语义计划降级成可验证、可执行的工具计划。

## 节点目标

固定边界：

```text
planner = 生成 SemanticPlan / tool_hints
plan_compiler = 生成 QueryPlan / ToolCallSpec
plan_validator = 检查计划是否合法
executor = 真正执行工具
```

`plan_compiler` 负责：

- 把 template workflow 或 generic tool hints 编译成 `QueryPlan`。
- 生成 `ToolCallSpec.name / arguments / depends_on / output_key`。
- 绑定 `$ref`、候选人来源、候选人池、排序结果和证据检索输入。
- 建立 `ArtifactBinding`，让 validator/executor 知道产物来源和消费者。
- 记录 compiler meta/debug，方便排查工具选择和引用绑定。

它不负责：

- 不重新判断 intent/scenario。
- 不生成自然语言答案。
- 不调用 tools。
- 不做 plan repair。
- 不在 hard filter 失败后私自扩大召回。

## 输入 / 输出

输入：

| 字段 | 来源 | 用途 |
|---|---|---|
| `question` | 用户问题 | 生成检索 query、TopK 限制、trace。 |
| `RouterOutput` | condition_normalizer 后 | conditions、context、requires flags、scenario。 |
| `SemanticPlan` | planner 或 template fallback | steps、tool_hints、semantic needs。 |
| `ExecutionDecision` | execution_policy | compiler 路径、workflow_name、scenarios。 |
| `session_context` | graph state | 绑定上一轮候选人、候选池、ranking top。 |
| `config` | YAML 加载结果 | compiler mode、tool policy、workflow template。 |
| tool registry | tools registry | 判断工具是否存在。 |

输出：

| 字段 | 说明 | 给谁用 |
|---|---|---|
| `QueryPlan.intent` | 可执行计划主 intent | validator/executor。 |
| `QueryPlan.sub_tasks` | compound 子任务 | validator/executor。 |
| `QueryPlan.tool_calls` | 单 intent 工具调用 | executor。 |
| `ToolCallSpec` | 工具名、参数、依赖、输出 key | executor。 |
| `ArtifactBinding` | 产物来源、类型、scope、消费者 | validator/debug。 |
| compiler meta | strategy、workflow、compiled tools、debug | trace/observability。 |

## 三条编译路径

### workflow_template

```text
ExecutionDecision.compiler = workflow_template
-> compile_with_workflow_templates
-> QueryPlan
```

稳定高频问题走这条路。它优先读取 `compiler_templates.yaml.workflows`，直接把 workflow 编译成工具调用。

### generic_tool_binding

```text
ExecutionDecision.compiler = generic_tool_binding
-> planner
-> SemanticPlan.tool_hints
-> compile_with_generic_tool_binding
-> QueryPlan
```

开放或未模板化问题走这条路。compiler 会对 tool hints 做 allowed/forbidden/registry/source contract 检查，通过后才生成 `ToolCallSpec`。

### hybrid_template_binding

```text
compiler mode = hybrid_template_binding
-> 如果 execution_policy 命中 workflow_template，走 template
-> 否则走 generic
```

这是生产常用模式：稳定路径用模板，不稳定路径走通用工具绑定。

## 文档阅读顺序

```text
1. README.md
2. PLAN_COMPILER_FLOW.md
3. YAML_USAGE.md
4. compiler.py
5. templates.py
6. trace.py
7. binding.py
8. artifacts.py
9. ../../core/rules/plan_building/
10. ../../core/inspection/plan_artifacts.py
```

注意：`binding.py` 和 `artifacts.py` 是兼容 wrapper，真正业务逻辑分别在 `core.rules.plan_building` 和 `core.inspection.plan_artifacts`。

## 验收命令

```bash
./.venv/bin/python -m compileall -q resume_query_ai_qa/nodes/plan_compiler
./.venv/bin/python resume_query_ai_qa/benchmarks/run_policy_contract_benchmark.py
./.venv/bin/python resume_query_ai_qa/benchmarks/run_plan_contract_benchmark.py
```
