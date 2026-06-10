# Plan Compiler Node

## 职责

`plan_compiler` 把 `SemanticPlan` 或 workflow template 降级成 executor 可执行的
`QueryPlan`。它是第一层允许创建 `ToolCallSpec` 的节点。

## 输入

| 输入 | 来源 | 用途 |
|---|---|---|
| `SemanticPlan` | planner 或 rule builder | 语义步骤和 tool hints。 |
| `ExecutionDecision` | execution_policy | template/generic、workflow、scenario。 |
| `RouterOutput` | normalizer 后 | normalized conditions、context policy。 |
| `session_context` | graph state | 绑定候选人、候选池、ranking top。 |
| tool registry/policy | config + registry | 判断工具是否存在、允许、优先或禁止。 |

## 输出

| 输出 | 用途 |
|---|---|
| `QueryPlan` | executor 执行。 |
| `SubTaskPlan[]` | compound 子任务。 |
| `ToolCallSpec[]` | 工具名、参数、依赖、输出 key。 |
| `ArtifactBinding[]` | canonical source、scope、producer/consumer。 |
| compiler meta | Debug 展示 accepted/rejected tool hints。 |

## 主流程

```text
workflow_template:
compiler_templates.yaml -> QueryPlan

generic_tool_binding:
SemanticPlan.tool_hints
-> tool_policy + registry + source contract
-> accepted ToolCallSpec / rejected hints
-> QueryPlan
```

## 失败 / Fallback

Compiler 不执行 repair。非法计划交给 `plan_validator` 分类。

| 场景 | 行为 | Trace 字段 |
|---|---|---|
| LLM hint 工具不存在 | reject hint | `compiler_decision.hint_tool_decisions` |
| hard filter source 不满足 scope | reject hint | `reason=source_scope_conflict` |
| compound source 不一致 | canonical source binding | `artifacts_summary`，完整 DTO 见 Debug `artifact_bindings` |
| 缺上下文绑定 | 编译出 context ref，validator 拦截 | `plan_validation_errors` |

## Trace 字段

- `strategy`
- `workflow_name`
- `compiled_tools`
- `filters`
- `ref_bindings`
- `artifacts_summary`
- Debug 深度模式：`debug.compiler_flags`、`debug.llm_tool_hint_scores`、`debug.artifact_bindings`、`debug.compiled_plan`

## 边界：能做 / 不能做

能做：

- 生成 QueryPlan 和 ToolCallSpec。
- 绑定 `$ref`、`candidate_ids`、scope。
- 建立 artifact lineage。
- 拒绝非法 tool hints。

不能做：

- 不重新判断 intent。
- 不调用工具。
- 不判断答案事实。
- 不在 hard filter 空结果后扩大召回。

## 扩展方式

- 新 workflow：更新 `compiler_templates.yaml`，补 compiler benchmark。
- 新工具：先注册 registry，再更新 `tool_policy.yaml`。
- 新 artifact：补 `ArtifactBinding`、validator、debug 展示。

## 验收 benchmark

```bash
.venv/bin/python resume_query_ai_qa/benchmarks/run_plan_contract_benchmark.py
.venv/bin/python resume_query_ai_qa/benchmarks/run_plan_contract_benchmark.py
.venv/bin/python resume_query_ai_qa/benchmarks/run_plan_contract_benchmark.py
```
