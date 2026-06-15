# Answer Rewrite Flow

## 阅读目标

这份文档只讲代码阅读线。`answer_rewrite` 的目标不是最终放行答案，而是在 `answer_validator` 失败后生成一个安全的 rewrite candidate，或者请求 rule fallback。

示例问题：

```text
金融候选人有几个，谁最强，依据是什么？
```

## Graph 入口

### `graph.nodes.answer_rewrite_node(state)`

输入来自 graph state：

```text
qa.question
qa.plan
qa.tool_results
qa.answer
current_answer_errors
current_answer_issues
use_llm
config
execution_decision
router_output
```

做什么：

```text
1. answer_rewrites += 1
2. qa.retry_count.aggregator_rewrite += 1
3. 调用 nodes.answer_rewrite.rewrite_answer(...)
4. 如果 answer != None，写回 qa.answer 和 qa.trace.aggregator_answer
5. 如果 answer == None 或 meta.engine == fallback_request，设置 answer_fallback_requested=True
6. 记录 trace
7. 返回 graph state 增量
```

输出给谁：

```text
answer_rewrite -> answer_validator
```

## 节点入口

### `rewrite_answer(...)`

位置：

```text
resume_query_ai_qa/nodes/answer_rewrite/node.py
```

执行顺序：

```text
classify_answer_repair_policy
-> previous_answer guard
-> rule_repair guard
-> generate_rewrite_candidate_with_meta
-> return answer/meta
```

### 1. `classify_answer_repair_policy(answer_issues)`

作用：

```text
根据 answer_validator 返回的 ValidationIssue.category 判断修复方式。
```

它不看自然语言，不重新理解问题。

结果：

```text
action=none
action=rule_repair
action=llm_rewrite
```

### 2. previous answer guard

如果没有上一版答案：

```text
previous_answer is None
-> return None, fallback_request
```

原因：

```text
rewrite 必须知道要修哪一版 answer。
如果上一版答案不存在，不能凭空 rewrite。
```

### 3. rule_repair guard

如果 policy 是 `rule_repair`：

```text
return None, fallback_request
```

注意：

```text
answer_rewrite 内部不直接重建 rule answer。
它只请求 graph 路由到 rule_answer_fallback。
```

为什么这么做：

```text
count/ranking/privacy/layout/evidence_id 这类问题通常属于硬合同问题。
直接丢弃不稳定答案，交给确定性 rule fallback 更稳。
```

### 4. `_issue_prompts(...)`

作用：

```text
把 ValidationIssue 转成 LLM rewrite prompt 可读的错误列表。
```

格式：

```text
[category/code/repairable=<bool>] message
```

如果没有结构化 issue：

```text
回退使用 answer_errors 字符串列表。
```

## Rewrite Candidate 生成

### `generate_rewrite_candidate_with_meta(...)`

位置：

```text
resume_query_ai_qa/core/answer_generation/generation.py
```

执行顺序：

```text
prepare_answer_inputs
-> render_grounded_answer
-> run_rewrite_flow
-> _meta_from_flow
-> return result.answer, meta
```

### `prepare_answer_inputs(...)`

重新构建 answer generation 的确定性输入：

```text
query_frame
layout_name
grounded_context
rule_draft
prompt_payload
selected_evidence
tool_results_summary
```

事实来源仍然是：

```text
ToolResult[]
```

### `render_grounded_answer(...)`

每次 rewrite 前都会先生成 grounded answer。

它有两个作用：

```text
1. 作为 grounding authority，提供 claims / used_evidence_refs / warnings
2. 作为 LLM 不可用或不合格时的稳定回退基础
```

## LLM Rewrite Flow

### `run_rewrite_flow(...)`

位置：

```text
resume_query_ai_qa/core/answer_generation/llm_flow.py
```

执行顺序：

```text
build_rewrite_prompt
-> rewrite_answer_with_llm
-> reject_if_fact_drifted
-> validate_layout_contract
-> merge_grounding
```

如果 `use_llm=False` 或 LLM 未启用：

```text
engine=rule_fallback_request
fallback_reason=llm_disabled
answer=None
```

### `build_rewrite_prompt(...)`

输入：

```text
payload
previous_answer
answer_errors
```

prompt 会要求 LLM：

```text
只修复 validator 指出的事实或结构问题
不新增 context 外事实
```

### `rewrite_answer_with_llm(...)`

调用结构化 LLM，输出 `AggregatedAnswer` draft。

注意：

```text
这个 draft 还不能直接相信。
```

### `reject_if_fact_drifted(...)`

检查 LLM 是否改了硬事实：

```text
count 是否丢失或改变
候选人是否越界
ranking 顺序是否改变
empty evidence 是否缺少免责声明
```

如果漂移：

```text
answer=None
mode=llm_rewrite_rejected
fallback_reason=fact_drift:<reason>
```

### `validate_layout_contract(...)`

检查 LLM 输出是否符合 layout rule draft。

如果 layout 违约：

```text
answer=None
mode=llm_rewrite_rejected
fallback_reason=layout_contract:<reason>
```

### `merge_grounding(...)`

如果 LLM rewrite 通过：

```text
answer.answer = LLM answer text
answer.claims = grounded.claims
answer.used_evidence_refs = grounded.used_evidence_refs
answer.warnings = grounded warnings + LLM warnings
```

这一步保证 rewrite 后仍然以 ToolResult 派生事实为权威。

## 回到 Validator

无论 rewrite 生成了什么：

```text
answer_rewrite -> answer_validator
```

如果 answer candidate 通过：

```text
answer_validator -> final
```

如果 candidate 失败，且 rewrite 次数到上限：

```text
answer_validator -> rule_answer_fallback
```

## 示例走读

问题：

```text
金融候选人有几个，谁最强，依据是什么？
```

上游可能产生：

```text
count_candidates = 3
rank_candidates = [张三, 李四, 王五]
search_candidate_evidence = [e1, e2]
```

如果 aggregator 答案写错：

```text
answer.answer = "金融候选人共有 4 位，李四最强。"
```

`answer_validator` 可能返回：

```text
count
ranking
```

`answer_rewrite` policy：

```text
count/ranking 在 rule_repair_categories 内
-> action=rule_repair
-> answer=None
-> fallback_request
```

graph 后续：

```text
answer_validator route -> rule_answer_fallback
-> answer_validator 复检
```

如果是未覆盖的表达类问题：

```text
action=llm_rewrite
-> LLM 生成新文本
-> drift/layout 校验
-> merge_grounding
-> answer_validator 复检
```

## 当前保留的复杂点

`answer_rewrite` 的名字容易误导：它不是所有错误都在本节点内部“修完”。

真实分工是：

```text
answer_rewrite.policy 决定是否值得尝试 rewrite
core.answer_generation 生成 rewrite candidate
rule_answer_fallback 负责确定性兜底答案
answer_validator 负责最终复检
```
