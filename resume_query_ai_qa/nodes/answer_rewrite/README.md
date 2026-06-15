# Answer Rewrite Node

## 一句话

`answer_rewrite` 是答案校验失败后的受控修复节点：

```text
answer_validator
-> answer_rewrite
-> answer_validator
```

它不是直接放行答案的节点。rewrite 后必须回到 `answer_validator` 复检。

## 架构位置

```text
aggregator
-> answer_validator
-> answer_rewrite
-> answer_validator
-> final / rule_answer_fallback / failed
```

`answer_rewrite` 只在 `answer_validator` 发现阻断错误后运行。它基于现有 `ToolResult[]`、上一版 `AggregatedAnswer` 和 validator errors 生成 rewrite candidate，或者请求进入 `rule_answer_fallback`。

## 节点目标

它做：

```text
读取 answer_validator 的 ValidationIssue
判断当前错误是否适合 rewrite
对未覆盖的表达类问题尝试 LLM rewrite
把 rewrite candidate 写回 qa.answer
让 graph 回到 answer_validator 复检
无法安全 rewrite 时请求 rule_answer_fallback
```

它不做：

```text
不调用工具
不修改 QueryPlan
不修改 ToolResult
不新增候选人、证据、排序或数量
不绕过 answer_validator
不在本节点内部直接生成最终 final
```

## 输入

| 输入 | 来源 | 用途 |
| --- | --- | --- |
| `question` | graph state / `qa.question` | 构建 rewrite prompt。 |
| `plan: QueryPlan` | plan_compiler | 保持 rewrite 仍回答原计划。 |
| `tool_results: ToolResult[]` | executor | grounded context 的唯一事实来源。 |
| `previous_answer: AggregatedAnswer` | aggregator / previous rewrite | 被修复的上一版答案。 |
| `answer_errors: list[str]` | answer_validator | 给 LLM 的错误摘要。 |
| `answer_issues: ValidationIssue[]` | answer_validator | policy 分类依据。 |
| `use_llm` | graph runner | 决定是否允许 LLM rewrite。 |
| `config` | YAML loader | 读取 repair policy 和 answer generation 配置。 |

## 输出

| 输出 | 含义 | 下游 |
| --- | --- | --- |
| `answer != None` | 生成了 rewrite candidate，写回 `qa.answer`。 | 回 `answer_validator` 复检。 |
| `answer == None` | 本节点不产出候选答案。 | graph 设置 `answer_fallback_requested`。 |
| `fallback_request` | 请求确定性 rule fallback。 | `rule_answer_fallback`。 |
| `meta.answer_repair_policy` | 记录分类动作、错误类别和原因。 | trace / diagnosis。 |
| `meta.aggregator_io` | LLM prompt/response/debug 摘要。 | debug trace。 |

## 主流程

```text
graph.nodes.answer_rewrite_node
-> rewrite_answer
-> classify_answer_repair_policy
-> _issue_prompts
-> generate_rewrite_candidate_with_meta
-> run_rewrite_flow
-> answer_validator
```

详细阅读线见 `ANSWER_REWRITE_FLOW.md`。

## Policy 怎么判断

`policy.py` 只看 `ValidationIssue`，不重新理解自然语言。

核心逻辑：

```text
没有 hard issue
-> action=none

所有 hard issue.category 都在 validation.yaml.answer_repair.rule_repair_categories
-> action=rule_repair
-> 本节点返回 answer=None
-> graph route 到 rule_answer_fallback

存在不在支持列表里的 category
-> action=llm_rewrite
-> 尝试生成 rewrite candidate
```

注意：

```text
rule_repair 不在 answer_rewrite 内部直接重建答案。
rule_repair 会返回 fallback_request，让 graph 路由到 rule_answer_fallback。
```

## LLM Rewrite 做什么

LLM rewrite 输入包括：

```text
question
previous_answer
validator errors
query_frame
rule_draft
grounded_context
selected_evidence
tool_results_summary
```

LLM 可以生成新的 `answer.answer` 文本，但不能改变工具事实。生成后会经过：

```text
reject_if_fact_drifted
validate_layout_contract
merge_grounding
```

最终：

```text
answer.answer 可以来自 LLM
answer.claims 来自 grounded
answer.used_evidence_refs 来自 grounded
answer.warnings 合并 grounded + LLM
```

## 失败与回退

| 场景 | 行为 |
| --- | --- |
| `previous_answer` 缺失 | 请求 fallback。 |
| validator issue 支持 rule repair | 请求 `rule_answer_fallback`。 |
| LLM disabled | rewrite candidate 为空，进入 fallback 路由。 |
| LLM 输出事实漂移 | 拒绝 candidate。 |
| LLM 输出 layout 违约 | 拒绝 candidate。 |
| LLM 异常 | 记录错误，candidate 为空。 |
| rewrite candidate 生成成功 | 写回答案，再回 `answer_validator`。 |

## 文档阅读顺序

```text
1. README.md
2. ANSWER_REWRITE_FLOW.md
3. YAML_USAGE.md
4. node.py
5. policy.py
6. core/answer_generation/generation.py
7. core/answer_generation/llm_flow.py
8. core/answer_generation/llm.py
```

## 验收

```bash
rg "Answer Rewrite|ANSWER_REWRITE_FLOW|YAML_USAGE|rewrite_answer|classify_answer_repair_policy|generate_rewrite_candidate_with_meta" resume_query_ai_qa/nodes/answer_rewrite
./.venv/bin/python -m compileall -q resume_query_ai_qa/nodes/answer_rewrite
./.venv/bin/python resume_query_ai_qa/benchmarks/run_policy_contract_benchmark.py
./.venv/bin/python resume_query_ai_qa/benchmarks/run_plan_contract_benchmark.py
./.venv/bin/python resume_query_ai_qa/benchmarks/run_runtime_contract_benchmark.py
```
