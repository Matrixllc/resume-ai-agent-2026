# Plan Compiler YAML Usage

这份文档是 YAML 字段地图，不是执行流程。执行流程看 `PLAN_COMPILER_FLOW.md`。

## compiler_templates.yaml

## execution_policy 使用的字段

这些字段主要用于 workflow 匹配，不是 plan_compiler 的主要编译内容：

| 字段 | 使用者 | 用途 |
|---|---|---|
| `workflows.*.priority` | execution_policy | workflow 匹配排序。 |
| `workflows.*.match.intent/intents` | execution_policy | 匹配主 intent。 |
| `workflows.*.match.required_sub_intents` | execution_policy | 匹配复合子 intent。 |
| `workflows.*.match.scenarios` | execution_policy | 匹配 scenario。 |
| `workflows.*.match.requires_scope` | execution_policy | 要求明确范围。 |

## plan_compiler 使用的字段

| 字段 | 使用位置 | 用途 |
|---|---|---|
| `workflows.*.tool_calls` | `sub_task_from_workflow_template` | 普通 workflow 的工具序列。 |
| `tool_calls[].tool` | template compiler | 工具名。 |
| `tool_calls[].default_output_key` | template compiler | 指定输出 key。 |
| `workflows.scoped_count_rank_evidence.sub_tasks` | `scoped_count_rank_evidence_plan` | 特殊复合 workflow 的子任务。 |
| `sub_tasks[].intent` | `_sub_task_from_declarative_spec` | 子任务 intent。 |
| `sub_tasks[].requires_jd_criteria` | `_sub_task_from_declarative_spec` | 子任务是否需要 JD 标准。 |
| `sub_tasks[].requires_evidence` | `_sub_task_from_declarative_spec` | 子任务是否需要证据。 |
| `sub_tasks[].tool_calls` | `_sub_task_from_declarative_spec` | 子任务工具调用声明。 |
| `tool_calls[].arguments` | `_resolve_binding` | 工具参数。 |
| `tool_calls[].depends_on` | `_sub_task_from_declarative_spec` | 工具依赖。 |
| `tool_calls[].output_key` | `_sub_task_from_declarative_spec` | 工具输出 key。 |
| `evidence.max_candidates` | `scoped_count_rank_evidence_plan` | 排序后查证据的候选人数。 |
| `notes` | template compiler | 写入 QueryPlan notes。 |

## $binding

`$binding` 是 template 编译期变量。

例子：

```yaml
arguments:
  candidates: {$ref: candidate_pool, path: [resume_identity], map: true}
tool: {$binding: ranking_criteria_tool}
```

plan_compiler 会把它解析成当前问题对应的真实值：

| binding | 来源 | 作用 |
|---|---|---|
| `filter_args` | `filter_args(question, router_output, session_context)` | 生成筛选参数。 |
| `ranking_criteria_tool` | `ranking_criteria_tool(router_output, config)` | 选择评分标准工具。 |
| `retrieval_query` | `tool_query(...)` | 生成证据检索 query。 |
| `workflow_evidence_max_candidates` | `evidence.max_candidates` | 控制证据检索候选数。 |

## filter_args 怎么来的

`arguments: {$binding: filter_args}` 不是直接写死成 `domains_any`。

它的意思是：

```text
去当前 workflow 编译时准备好的 bindings 字典里，取 filter_args 这个变量的值。
```

特殊复合 workflow 编译时会先准备：

```python
bindings = {
    "filter_args": filter_args(question, router_output, session_context),
    "ranking_criteria_tool": ranking_criteria_tool(router_output, config),
    "retrieval_query": tool_query(question, "candidate_ranking", router_output),
    "workflow_evidence_max_candidates": 3,
}
```

其中：

```python
filter_args(question, router_output, session_context)
```

会读取：

```python
router_output.normalized_conditions
```

再调用：

```python
filter_arguments_from_conditions(router_output.normalized_conditions, question)
```

把标准化条件翻译成 `filter_candidates` 工具能看懂的参数。

完整链路：

```text
condition_normalizer
-> RouterOutput.normalized_conditions
-> filter_args(...)
-> filter_arguments_from_conditions(...)
-> bindings["filter_args"]
-> _resolve_binding({"$binding": "filter_args"})
-> ToolCallSpec.arguments
```

例子：

```text
用户问题：金融候选人有几个？
```

condition_normalizer 产出：

```python
NormalizedCondition(
    type="domain",
    normalized_value="金融",
)
```

`filter_args(...)` 产出：

```python
{
    "domains_any": ["金融"]
}
```

所以 YAML：

```yaml
arguments: {$binding: filter_args}
```

最终变成：

```python
ToolCallSpec(
    name="filter_candidates",
    arguments={
        "domains_any": ["金融"]
    },
    output_key="candidate_pool",
)
```

常见条件到工具参数的映射：

| NormalizedCondition | filter_args 结果 |
|---|---|
| `domain=金融` | `domains_any=["金融"]` |
| `domain=金融`，且问题含“同时属于/兼具/都具备” | `domains_all=["金融"]` |
| `skill=Python` | `skills_all=["Python"]` |
| `concept=推荐系统` | `concepts_all=["推荐系统"]` |
| `major=计算机` | `education_keywords=["计算机"]` |
| `keyword=发票` | `keywords=["发票"]` |

如果当前问题还引用了上下文候选人池，例如“这些人里谁会 Python”，`filter_args` 后面还会经过：

```python
with_context_candidate_ids(args, router_output, session_context)
```

这会额外补：

```python
{
    "candidate_ids": [...]
}
```

一句话：

```text
$binding 只是变量引用。
filter_args 才是真正把 normalized_conditions 翻译成工具 arguments 的函数。
```

## validator 使用的字段

这些字段不是 compiler 主流程判断，但后续 validator 会使用：

| 字段 | 使用者 | 用途 |
|---|---|---|
| `artifact_contracts` | plan_validator | 检查工具参数引用是否符合产物合同。 |
| `artifact_type` | validator/debug | 描述 workflow 产物类型。 |
| `tool_calls[].produces` | validator/debug | 声明工具产物。 |
| `tool_calls[].consumes` | validator/debug | 声明工具消费的产物。 |

## tool_policy.yaml

plan_compiler 直接使用 `intent_tools`：

| 字段 | 使用位置 | 用途 |
|---|---|---|
| `intent_tools.*.allowed_tools` | generic compiler | 工具白名单。 |
| `intent_tools.*.preferred_tools` | `tool_hints_for_generic_step` | 生成 policy hints。 |
| `intent_tools.*.preferred_tool_hints` | `tool_hints_for_generic_step` | 生成带置信度的 policy hints。 |
| `intent_tools.*.forbidden_tools` | generic compiler | 工具黑名单。 |
| `intent_tools.*.scenarios.*` | config 查询方法 | scenario 级覆盖。 |

generic 编译时判断顺序：

```text
hint 是否 forbidden
-> 工具是否在 registry
-> 工具是否 allowed
-> candidate source 是否合规
-> required template tool 是否满足
-> source contract 是否冲突
```

## tools metadata

`tool_policy.yaml.tools.*` 会通过 config/helper 间接影响 compiler：

| 字段 | 用途 |
|---|---|
| `produces` | 生成 artifact binding。 |
| `default_output_key` | 默认输出 key。 |
| `bind_primary_artifact` | 是否绑定主产物。 |
| `scope` | candidate source scope 判断。 |
| `binding_kind` | 默认工具选择。 |
| `roles` | 按角色查找默认工具。 |

## intents.yaml

plan_compiler 会通过 config 间接读取：

```text
semantic_defaults_for_intent(intent, scenario)
```

主要用于 template 子任务 fallback：

```text
SubTaskPlan.requires_jd_criteria
SubTaskPlan.requires_evidence
```

注意：

- intent/scenario 的主要权威收口在 router finalizer 和 planner。
- compiler 这里只是为了让生成的 `SubTaskPlan` 字段完整。

## .env compiler flags

读取位置：

```text
config.compiler_flags()
```

变量：

| 变量 | 用途 |
|---|---|
| `RESUME_QA_WORKFLOW_TEMPLATE_COMPILER_ENABLED` | 是否启用 workflow template 能力；开启时走 hybrid，未配置或关闭时走 pure generic。 |

内部 mode：

```text
true  -> hybrid_template_binding
false -> generic_tool_binding
```

## 输出字段来源表

| QueryPlan 字段 | 主要来源 |
|---|---|
| `intent` | `SemanticPlan.intent` 或首个 `SubTaskPlan.intent` |
| `is_compound` | `SemanticPlan.intent == compound` |
| `sub_tasks` | template sub_tasks 或 generic step 编译结果 |
| `tool_calls` | template tool_calls 或 generic accepted hints |
| `artifact_bindings` | `with_artifact_bindings` 根据工具产物/参数生成 |
| `constraints.ranking_output_limit` | `ranking_output_limit(question)` |
| `notes` | compiler path / template notes |

| ToolCallSpec 字段 | 主要来源 |
|---|---|
| `name` | template `tool` 或 accepted tool hint |
| `arguments` | `generic_call_for_tool` 或 template `arguments` |
| `depends_on` | template 声明或 builder 生成 |
| `output_key` | template `output_key/default_output_key` 或 config default |

## 排查顺序

如果 QueryPlan 不符合预期，按这个顺序排查：

```text
1. execution_policy 是否选择了预期 compiler/workflow
2. SemanticPlan.steps/tool_hints 是否正确
3. compiler flags 当前 mode 是否正确
4. compiler_templates.yaml workflow 是否命中
5. tool_policy.yaml allowed/preferred/forbidden 是否正确
6. tool registry 是否注册了目标工具
7. generic_call_for_tool 是否生成了目标参数
8. with_structured_refs 是否生成正确 $ref
9. with_artifact_bindings 是否生成正确产物绑定
10. plan_validator 是否因为合同问题拦截
```
