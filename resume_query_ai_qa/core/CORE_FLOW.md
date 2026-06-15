# Core Flow

这份文档按运行链路解释 `core` 怎么被调用。  
`core` 不是主流程编排器；它是被 graph、nodes、tools 复用的底座。

## 1. 总链路

```text
graph.run
-> load_config
-> graph nodes
-> core.rules / core.inspection / core.answer_generation / core.llm
-> tools
-> validators
-> final answer
```

## 2. 配置进入运行时

```text
graph.runner.run
-> core.config.load_config
-> configs/*.yaml
-> ResumeQAConfig
-> core.config_validation.validate_config_structure
-> load_project_env
-> qa.config
```

后续 node 不应该自己解释 YAML shape，而应该通过：

```text
config.allowed_tools_for_intent(...)
config.semantic_defaults_for_intent(...)
config.default_output_key(...)
config.retry_limit(...)
```

## 3. Router / Policy / Planner 规则线

```text
router node
-> core.rules.condition_rules
-> core.rules.candidate_mentions
-> core.rules.context_resolver
-> core.rules.execution_policy_rules
```

```text
execution_policy node
-> core.rules.execution_policy_rules.resolve_execution_decision
-> compiler_templates.yaml / scenarios.yaml via ResumeQAConfig
```

```text
planner node
-> core.rules.semantic_plan
-> SemanticPlan
```

这些规则只做 deterministic 判断，不调用工具，不调用 LLM。

## 4. Plan 编译规则线

```text
plan_compiler / plan_repair / execution_repair
-> core.rules.plan_building
-> QueryPlan / ToolCallSpec
```

核心职责：

```text
builders.py       = 按 binding_kind 生成 ToolCallSpec
query_args.py     = 从 RouterOutput / context 生成工具参数
refs.py           = $ref / structured ref 转换
source_policy.py  = canonical candidate source 和 source 复用
orchestration.py  = sub-task / tool sequence 编排规则
hints.py          = planner tool hints 去重与排序
```

## 5. Validator / Inspection 线

```text
plan_validator
-> core.inspection.plan_inspection
-> core.inspection.plan_artifacts
```

```text
execution_validator / answer_validator
-> core.inspection.result_inspection
-> core.rules.behavior_contract
-> core.rules.evidence_policy
```

inspection 只读 plan/result，不修 plan、不调用工具。

## 6. Answer Generation 线

```text
aggregator node
-> core.answer_generation.aggregate_answer_with_meta
-> prepare_answer_inputs
-> build_query_frame
-> infer_answer_layout
-> build_answer_context
-> render_grounded_answer
-> run_fill_flow
-> AggregatedAnswer
```

```text
answer_rewrite node
-> core.answer_generation.generate_rewrite_candidate_with_meta
-> render_grounded_answer
-> run_rewrite_flow
-> answer_validator
```

关键不变量：

```text
ToolResult facts are authority.
Grounded claims / evidence refs are authority.
LLM may generate answer text, but must pass drift/layout checks.
```

## 7. LLM Structured Draft 线

```text
router / planner / answer_generation
-> core.llm.invoke_structured
-> core.llm.client
-> provider model
-> Pydantic schema validation
-> normalized payload
```

LLM client 只负责 provider、prompt、结构化返回和 payload cleanup。  
业务节点仍要 guard / finalizer / validator 收口。

## 8. Data Access 线

```text
core.rules / tools helper
-> core.data_access
-> ResumeSqlReader / ResumeVectorReader / candidate_index
```

data_access 只读底层数据，不生成答案、不规划工具链。

## 9. 怎么从问题排查

intent 错：

```text
nodes/router
core.rules.condition_rules
core.rules.candidate_mentions
```

workflow 错：

```text
nodes/execution_policy
core.rules.execution_policy_rules
configs/compiler_templates.yaml
```

tool 参数错：

```text
nodes/plan_compiler
core.rules.plan_building
core.inspection.plan_artifacts
```

工具结果 lineage 错：

```text
nodes/execution_validator
core.inspection.result_inspection
core.rules.behavior_contract
```

答案文本/claim 错：

```text
nodes/aggregator
core.answer_generation
nodes/answer_validator
```

LLM shape 错：

```text
core.llm.client
core.llm.client.payload_normalization
core.llm.client.schema_contracts
```
