# Rule Answer Fallback Node

`rule_answer_fallback` 在 LLM 答案无法通过 grounding 或 answer validator 时，使用确定性
规则答案重新生成 `AggregatedAnswer`。

它是 answer 层 fallback，不是重新检索或重新规划：

- 事实仍只来自原有 `ToolResult`。
- 不改变人数、名单、排名和证据。
- 生成后必须重新进入 `answer_validator`。
- trace 中记录 `fallback_reason=deterministic_rule_fallback`。

规则答案的 source of truth 位于 `resume_query_ai_qa/core/answer_generation/`。
