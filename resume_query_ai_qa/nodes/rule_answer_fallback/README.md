# Rule Answer Fallback Node

`rule_answer_fallback` 是答案层的确定性兜底节点。它在 LLM answer 或 answer rewrite 不能通过
grounding / answer validator 时，用规则 renderer 重新生成 `AggregatedAnswer`。

## 架构位置

```text
aggregator / answer_rewrite
-> answer_validator
-> rule_answer_fallback
-> answer_validator
```

它不是重新检索、重新规划或重新执行工具。它只消费当前轮已经验证过的 `ToolResult[]`。

## 节点目标

把“不安全或不合格的自然语言答案”替换成确定性规则答案：

```text
question + QueryPlan + ToolResult[] + grounded context
-> rule AggregatedAnswer
-> answer_validator
```

核心目标不是更好看，而是更安全：

- 不新增事实。
- 不改变数量。
- 不改变候选人名单。
- 不改变排名。
- 不伪造 evidence id。

## 输入

| 输入 | 来源 | 用途 |
| --- | --- | --- |
| `question` | 用户原始问题 | 决定答案表达对象。 |
| `plan` | plan_compiler / plan_validator | 知道当前工具链和输出含义。 |
| `tool_results` | executor / execution_validator | 唯一事实来源。 |
| `previous_answer` | aggregator 或 answer_rewrite | 仅用于 trace 对比，不作为事实权威。 |
| `answer_validator issues` | answer_validator | 说明为什么需要 fallback。 |

## 输出

| 输出 | 含义 |
| --- | --- |
| `AggregatedAnswer` | 规则生成的答案候选。 |
| `fallback_reason` | trace 中记录 fallback 原因。 |
| `warnings` | 保留或追加 fallback 相关提示。 |

输出后必须回到 `answer_validator`。fallback 不是特权通道，不能绕过出口检查。

## 它做什么

- 调用 `core.answer_generation` 中的确定性 renderer。
- 基于工具事实重建 answer / claims / used_evidence_refs。
- 记录 `fallback_reason=deterministic_rule_fallback`。
- 把结果交回 `answer_validator` 复检。

## 它不做什么

- 不调用 tools。
- 不扩大召回。
- 不重新生成 `QueryPlan`。
- 不调用 LLM。
- 不修复工具结果。
- 不直接返回 final。

## 和 Aggregator / Answer Rewrite 的边界

| 节点 | 作用 |
| --- | --- |
| `aggregator` | 首次组织答案，LLM 可基于 grounded payload 生成文本。 |
| `answer_validator` | 判断答案是否满足事实、证据、隐私、layout 合同。 |
| `answer_rewrite` | 对部分表达问题尝试 LLM rewrite，rewrite 后仍回 validator。 |
| `rule_answer_fallback` | 当 LLM 文本不合格或 rewrite 不安全时，用规则答案兜底。 |

## 示例

用户问：

```text
金融候选人有几个，谁最强，依据是什么？
```

工具结果已经得到：

```text
filter_candidates -> candidate_pool
count_candidates -> candidate_count
rank_candidates -> ranking
search_candidate_evidence -> evidence
```

如果 LLM answer 把候选人数写错，或把第二名写成第一名：

```text
answer_validator
-> count/ranking issue
-> rule_answer_fallback
-> 用 ToolResult 重新渲染规则答案
-> answer_validator 复检
-> final
```

这条路径牺牲一点表达自由度，换取事实安全。

## 验收

```bash
.venv/bin/python -m compileall -q resume_query_ai_qa
.venv/bin/python resume_query_ai_qa/benchmarks/run_runtime_contract_benchmark.py
```
