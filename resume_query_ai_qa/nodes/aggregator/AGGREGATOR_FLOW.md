# Aggregator Flow

这个文档按真实代码路径讲 aggregator。

核心数据流：

```text
QueryPlan + ToolResult[] + RouterOutput + ExecutionDecision
-> question + rule_draft + grounded_context + evidence
-> AggregatedAnswer
```

## 1. `graph.nodes.aggregator_node`

位置：

```text
resume_query_ai_qa/graph/nodes.py
```

作用：

```text
graph 层入口，调用 aggregate_answer_with_meta()，把答案和 meta 写回 qa state。
```

它传入：

- `qa.question`
- `qa.plan`
- `qa.tool_results`
- `config`
- `use_llm`
- `execution_decision`
- `router_output`

它写回：

- `qa.answer`
- `qa.trace.aggregator_answer`
- decision log / debug meta

## 2. `aggregate_answer_with_meta`

位置：

```text
core/answer_generation/generation.py
```

主入口。

流程：

```text
inputs = prepare_answer_inputs(...)
grounded = render_grounded_answer(inputs)
result = run_fill_flow(inputs, grounded, config, use_llm=use_llm)
meta = _meta_from_flow(...)
return result.answer or grounded, meta
```

关键点：

```text
render_grounded_answer 每次都会先生成。
LLM 可用时，grounded 是事实权威底座。
LLM 不可用或不合格时，grounded 是 fallback answer。
```

## 3. `prepare_answer_inputs`

位置：

```text
core/answer_generation/orchestration.py
```

作用：

```text
准备答案生成所需的确定性输入，不调用 LLM，不改 ToolResult。
```

内部步骤：

```text
build_query_frame
-> infer_answer_layout
-> build_answer_context
-> build_rule_draft
-> build_prompt_payload
```

输出 `AnswerInputs`：

- `query_frame`
- `layout_name`
- `layout_config`
- `layout_reason`
- `context`
- `rule_draft`
- `payload`

## 4. `build_query_frame`

位置：

```text
core/answer_generation/task.py
```

作用：

```text
把 question / QueryPlan / ToolResult / scenario 转成回答任务框架。
```

它会得到：

- `intents`
- `scenarios`
- `successful_tools`
- `task_type`
- `freedom_level`
- `default_layout`
- `slots`

任务类型来自：

```text
aggregator_tasks.yaml.task_types
```

例子：

```text
candidate_ranking + rank_candidates
-> task_type = candidate_decision_answer
```

## 5. `infer_answer_layout`

位置：

```text
core/answer_generation/layout.py
```

作用：

```text
根据 task_type / freedom_level / successful_tools / trigger_terms 选择回答布局。
```

布局来自：

```text
answer_layouts.yaml.layouts
```

例子：

```text
candidate_decision_answer + count_candidates + rank_candidates
-> layout = decision_chain
```

## 6. `build_answer_context`

位置：

```text
core/answer_generation/context.py
```

作用：

```text
只从 ToolResult[] 收集事实，形成 grounded_context。
```

会收集：

- `count`
- `candidates`
- `profiles`
- `projects`
- `evidence`
- `ranking`
- `comparison`
- `business_limits`
- `empty_flags`
- `insufficient_info_reasons`

这是 LLM 可使用事实的主要来源。

## 7. `build_rule_draft`

位置：

```text
core/answer_generation/draft.py
```

作用：

```text
把选中的 YAML layout 转成答案框架合同。
```

包含：

- `sections`
- `required_sections`
- `titles`
- `required_title_sections`
- `first_section`
- `section_contract`
- `writing_rules`
- `hard_constraints`
- `claim_contract`

这个 `rule_draft` 会进入 LLM prompt。

## 8. `build_prompt_payload`

位置：

```text
core/answer_generation/prompt_payload.py
```

作用：

```text
组装 LLM 输入。
```

payload 包含：

```text
question
query_frame
rule_draft
grounded_context
selected_evidence
tool_results_summary
```

所以 LLM 不是只看规则答案，而是看：

```text
用户问题 + 回答框架 + 工具事实 + 证据
```

## 9. `render_grounded_answer`

位置：

```text
core/answer_generation/orchestration.py
```

作用：

```text
用规则 renderer 生成 grounded answer，并做事实权威收口。
```

内部：

```text
rule_answer = render_rule_answer(...)
return grounded_authority(rule_answer, context, layout_name)
```

它不是只在 fallback 时执行，而是每次都先执行。

## 10. `render_rule_answer`

位置：

```text
core/answer_generation/renderers/router.py
```

作用：

```text
根据 task_type / layout_name 路由到确定性 renderer。
```

例子：

- `candidate_decision_answer` -> `render_decision`
- `candidate_comparison_answer` -> `render_comparison`
- `candidate_profile_answer` -> `render_profile_or_fact`
- `candidate_set_answer` -> `render_candidate_set`
- fallback -> `render_open_grounded`

## 11. `grounded_authority`

位置：

```text
core/answer_generation/orchestration.py
```

作用：

```text
把 claims / used_evidence_refs / warnings 收口到 grounded context。
```

输出：

```text
answer = rule_answer.answer
claims = build_grounded_claims(context)
used_evidence_refs = build_used_evidence_refs(context)
warnings = layout warnings + empty evidence warnings
```

这是后续 LLM merge 的事实权威来源。

## 12. `run_fill_flow`

位置：

```text
core/answer_generation/llm_flow.py
```

作用：

```text
如果 LLM 可用，让 LLM 根据 payload 生成 answer 文本；否则使用 grounded。
```

流程：

```text
answer = grounded
if use_llm and is_llm_enabled(config):
    generated = fill_answer_with_llm(payload)
    rejection_reason = fact drift / layout contract check
    if rejected:
        answer = grounded + warning
    else:
        answer = merge_grounding(generated, grounded)
return LLMFlowResult
```

## 13. `fill_answer_with_llm`

位置：

```text
core/answer_generation/llm.py
```

作用：

```text
调用 LLM，要求输出 AggregatedAnswer JSON。
```

prompt 明确要求：

```text
根据 layout rule draft 和 grounded context 生成中文答案
只能使用 grounded_context 中的事实
claims 和 used_evidence_refs 可以留空，系统会基于 context 回填
```

## 14. `reject_if_fact_drifted`

位置：

```text
core/answer_generation/llm.py
```

作用：

```text
检查 LLM 输出有没有改事实。
```

会拒绝：

- count 缺失或改变
- unknown candidate claim
- ranking 顺序改变
- empty evidence 没有说明不能确认

## 15. `merge_grounding`

位置：

```text
core/answer_generation/llm.py
```

作用：

```text
保留 LLM 的 answer 文本，但 claims / evidence refs 回到 grounded。
```

最终：

```text
answer = LLM answer
claims = grounded.claims
used_evidence_refs = grounded.used_evidence_refs
warnings = grounded.warnings + LLM warnings
```

## 16. `_meta_from_flow`

位置：

```text
core/answer_generation/generation.py
```

作用：

```text
把 LLM flow 结果整理成 graph trace meta。
```

包括：

- engine
- fallback_reason
- llm identity
- aggregator_io
- task/layout/context summary
- rule_draft

## 示例：数量 + 排名 + 依据

问题：

```text
金融候选人有几个，谁最强，依据是什么？
```

工具结果：

```text
count_candidates -> 3
rank_candidates -> [张三, 李四, 王五]
search_candidate_evidence -> EvidenceRef[]
```

生成过程：

```text
build_query_frame
-> task_type = candidate_decision_answer

infer_answer_layout
-> layout = decision_chain

build_answer_context
-> count = 3
-> ranking = [张三, 李四, 王五]
-> evidence = [...]

build_rule_draft
-> sections = conclusion / count / ranking / key_reason / main_basis

build_prompt_payload
-> question + rule_draft + grounded_context + selected_evidence

render_grounded_answer
-> grounded claims: count=3, ranking=[张三, 李四, 王五], evidence refs

run_fill_flow
-> LLM 生成 answer 文本
-> merge_grounding 收口 claims / evidence refs
```

最终：

```text
AggregatedAnswer.answer = LLM 或 grounded 的答案文本
AggregatedAnswer.claims = grounded claims
AggregatedAnswer.used_evidence_refs = grounded evidence refs
```
