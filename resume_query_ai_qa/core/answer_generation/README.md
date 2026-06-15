# Answer Generation Package

`core/answer_generation/` 是 aggregator / answer_rewrite / rule fallback 的真实答案生成核心。

一句话：

```text
answer_generation = question + QueryPlan + ToolResult facts + YAML layout -> AggregatedAnswer
```

它不调用 tools，不重新规划，不查库。事实只能来自已经验证过的 `ToolResult[]`。

## 主流程

```text
aggregate_answer_with_meta
-> prepare_answer_inputs
-> build_query_frame
-> infer_answer_layout
-> build_answer_context
-> build_rule_draft
-> build_prompt_payload
-> render_grounded_answer
-> run_fill_flow
-> AggregatedAnswer
```

rewrite 流程：

```text
generate_rewrite_candidate_with_meta
-> prepare_answer_inputs
-> render_grounded_answer
-> run_rewrite_flow
-> answer_validator
```

## 文件地图

| 文件 | 职责 |
| --- | --- |
| `generation.py` | 对外 facade，聚合 answer/rewrite/fallback API |
| `orchestration.py` | 准备 deterministic inputs、grounded authority、trace meta |
| `task.py` | 根据 query/plan/result 构造 QueryFrame |
| `layout.py` | 根据 YAML 选择和校验 answer layout |
| `context.py` | 从 ToolResult 收集 grounded context |
| `draft.py` | 构造 rule draft / section contract / claim contract |
| `prompt_payload.py` | 构造 LLM 输入 payload |
| `grounding.py` | grounded claims、evidence refs、candidate/ranking authority |
| `llm_flow.py` | LLM fill/rewrite 控制流，处理 drift/layout rejection |
| `llm.py` | prompt、structured LLM 调用、fact drift、merge grounding |
| `fallback.py` | hard fallback answer |
| `renderer.py` / `renderers/` | deterministic rule answer renderer |
| `logging.py` | aggregator meta/log summary |

## 关键边界

`render_grounded_answer` 每次都会先执行。

它有两个身份：

```text
fallback answer
grounding authority
```

LLM 成功时：

```text
answer = LLM answer text
claims = grounded claims
used_evidence_refs = grounded evidence refs
warnings = grounded + LLM warnings
```

LLM 失败时：

```text
answer = grounded rule answer
claims = grounded claims
used_evidence_refs = grounded evidence refs
warnings = fallback reason
```

## 它不做什么

- 不调用工具。
- 不改 QueryPlan。
- 不新增候选人事实。
- 不重排 ranking。
- 不绕过 answer_validator。

## 排查地图

| 问题 | 看哪里 |
| --- | --- |
| answer layout 选错 | `layout.py`、`answer_layouts.yaml` |
| LLM payload 不清楚 | `prompt_payload.py` |
| claim/evidence refs 来源不清 | `grounding.py` |
| rule answer 文案不对 | `renderers/` |
| LLM 漂移/拒绝 | `llm_flow.py`、`llm.py` |
