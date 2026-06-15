# Plan Compiler Flow

这份文档只讲代码阅读线。YAML 字段地图看 `YAML_USAGE.md`，节点总览看 `README.md`。

## 阅读入口

```text
compiler.py
-> templates.py
-> trace.py
-> binding.py / artifacts.py wrappers
-> core/rules/plan_building
-> core/inspection/plan_artifacts.py
```

## 1. compile_semantic_plan_with_meta

位置：

```text
nodes/plan_compiler/compiler.py
```

输入：

- `question`
- `router_output`
- `semantic_plan`
- `session_context`
- `config`
- `decision`

输出：

- `QueryPlan`
- compiler meta

执行过程：

```text
load config
-> config.compiler_flags()
-> decision or resolve_execution_decision(...)
-> normalize_semantic_plan(...)
-> 根据 compiler mode 分流
```

分流：

```text
generic_tool_binding
-> compile_with_generic_tool_binding

hybrid_template_binding
-> compile_with_hybrid_template_binding

workflow_template
-> compile_with_workflow_templates
-> compiler_trace_meta
```

为什么先 `normalize_semantic_plan`：

- 即使 template 路径绕过 planner，compiler 也要拿到结构一致的 `SemanticPlan`。
- LLM draft 不能直接进入工具编译，必须重新对齐 `RouterOutput` 和 YAML。

## 2. compile_semantic_plan

位置：

```text
nodes/plan_compiler/compiler.py
```

职责：

```text
只返回 QueryPlan，不返回 meta。
```

它是 `compile_semantic_plan_with_meta` 的简化入口。

## 3. compile_with_hybrid_template_binding

位置：

```text
nodes/plan_compiler/compiler.py
```

职责：

```text
在 hybrid mode 下，根据 ExecutionDecision 决定走 template 还是 generic。
```

逻辑：

```text
decision.compiler == workflow_template
-> compile_with_workflow_templates
-> template meta
-> 记录 template_rejected_hints

否则
-> compile_with_generic_tool_binding
-> generic meta
```

## 4. compile_with_workflow_templates

位置：

```text
nodes/plan_compiler/templates.py
```

职责：

```text
把 compiler_templates.yaml 中的 workflow 编译成 QueryPlan。
```

执行过程：

```text
先尝试 scoped_count_rank_evidence_plan
-> 命中则直接返回特殊复合计划

如果 SemanticPlan.intent == compound
-> 每个 step 生成一个 SubTaskPlan
-> reuse_candidate_source_for_count_list
-> QueryPlan(intent=compound)

否则
-> 单 intent 生成一个 SubTaskPlan
-> QueryPlan(tool_calls=...)

最后
-> ranking output limit
-> canonical source binding
-> structured refs
-> artifact bindings
```

## 5. scoped_count_rank_evidence_plan

位置：

```text
nodes/plan_compiler/templates.py
```

职责：

```text
处理“有几个 + 谁最强 + 依据是什么”这种稳定复合 workflow。
```

读取：

```text
compiler_templates.yaml.workflows.scoped_count_rank_evidence
```

生成 bindings：

```text
filter_args
ranking_criteria_tool
retrieval_query
workflow_evidence_max_candidates
```

再把 YAML 里的 `sub_tasks` 编译成 `SubTaskPlan[]`。

## 6. _sub_task_from_declarative_spec

位置：

```text
nodes/plan_compiler/templates.py
```

职责：

```text
把 workflow sub_tasks 的声明式 YAML 转成 SubTaskPlan。
```

它会生成：

```text
ToolCallSpec.name
ToolCallSpec.arguments
ToolCallSpec.depends_on
ToolCallSpec.output_key
```

## 7. _resolve_binding

位置：

```text
nodes/plan_compiler/templates.py
```

职责：

```text
解析 YAML 里的 {$binding: xxx}。
```

例如：

```yaml
tool: {$binding: ranking_criteria_tool}
```

会变成：

```text
load_default_jd_criteria 或 load_general_resume_criteria
```

## 8. compile_with_generic_tool_binding

位置：

```text
nodes/plan_compiler/compiler.py
```

职责：

```text
把 SemanticPlan.tool_hints 编译成真实 ToolCallSpec。
```

执行过程：

```text
get_tool_registry
-> 遍历 SemanticPlan.steps
-> 读取 scenario
-> 读取 allowed / forbidden / required tools
-> tool_hints_for_generic_step
-> 逐个 hint 检查
   - forbidden?
   - registry exists?
   - allowed?
   - candidate_filter 是否是 candidate source tool?
   - required template tool 是否满足?
   - candidate source 是否冲突?
-> generic_call_for_tool 生成 ToolCallSpec
-> candidate source 复用 / ref root 替换
-> open_recall 时可能插入 hybrid_source_call
-> 组装 SubTaskPlan
-> 组装 QueryPlan
-> structured refs
-> artifact bindings
-> compiler_trace_meta
```

注意：

- LLM 或 policy 的 tool hints 只是候选。
- 只有通过 registry、allowed、forbidden、source contract 后，才会变成 `ToolCallSpec`。

## 9. tool_hints_for_generic_step

位置：

```text
nodes/plan_compiler/compiler.py
```

职责：

```text
合并 SemanticStep 自带 hints、tool_policy hints、workflow required tools。
```

顺序：

```text
policy hints
-> 过滤 forbidden
-> allowed + template_tool_names 生成 compiler_required hints
-> dedupe
```

## 10. refresh_artifact_bindings

位置：

```text
nodes/plan_compiler/compiler.py
```

职责：

```text
重新刷新 QueryPlan 的 structured refs 和 artifact bindings。
```

主要给 repair 或外部调用使用。

## 11. compiler_trace_meta

位置：

```text
nodes/plan_compiler/trace.py
```

职责：

```text
生成 trace/debug 信息，不改变 QueryPlan。
```

输出包括：

```text
strategy
workflow_name
compiled_tools
filters
artifacts_summary
debug.compiler_flags
debug.execution_scenarios
debug.llm_tool_hints
debug.artifact_bindings
debug.compiled_plan
```

## 示例

问题：

```text
金融候选人有几个，谁最强，依据是什么？
```

上游可能产出：

```text
ExecutionDecision.compiler = workflow_template
workflow_name = scoped_count_rank_evidence
SemanticPlan.intent = compound
SemanticPlan.steps = [candidate_count, candidate_ranking, evidence_question]
RouterOutput.normalized_conditions = domain: 金融
```

编译过程：

```text
compile_semantic_plan_with_meta
-> mode = hybrid_template_binding
-> compile_with_workflow_templates
-> scoped_count_rank_evidence_plan
-> 读取 compiler_templates.yaml 的 sub_tasks
-> 解析 {$binding: filter_args}
-> 解析 {$binding: ranking_criteria_tool}
-> 解析 {$binding: retrieval_query}
-> 生成 QueryPlan(intent=compound)
```

输出工具链类似：

```text
filter_candidates -> candidate_pool
count_candidates(candidate_pool)
load_default_jd_criteria -> criteria
score_candidates_for_jd(candidate_pool, criteria) -> scores
rank_candidates(scores) -> ranked_candidates
search_candidate_evidence(ranked_candidates) -> candidate_evidence
```
