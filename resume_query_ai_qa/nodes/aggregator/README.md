# Aggregator Node

一句话：`aggregator` 把已验证的 `ToolResult[]`、用户问题和 YAML 回答框架组织成 `AggregatedAnswer`。

更准确的心智模型：

```text
aggregator = query + YAML 回答框架 + ToolResult 事实 + evidence -> AggregatedAnswer
```

这里的 LLM 不是只润色规则答案。LLM 的输入包含：

```text
question
query_frame
rule_draft
grounded_context
selected_evidence
tool_results_summary
```

LLM 根据这些内容生成最终 `answer` 文本；系统再用 grounded rule answer 收口 `claims`、`used_evidence_refs` 和 `warnings`。

## 架构位置

```text
execution_validator
-> aggregator
-> answer_validator
-> answer_rewrite / rule_answer_fallback / final
```

前后节点边界：

```text
execution_validator = 放行已验证工具结果
aggregator = ToolResult[] -> AggregatedAnswer
answer_validator = 校验最终答案事实、证据、布局
answer_rewrite = 修正不合格答案
```

## 代码位置

`nodes/aggregator` 主要是兼容 wrapper / graph import facade。

真实答案生成逻辑在：

```text
resume_query_ai_qa/core/answer_generation/
```

因此阅读时不要只停在 `nodes/aggregator`，要继续看 `core/answer_generation`。

## 节点目标

`aggregator` 做四件事：

- 从 `ToolResult[]` 里整理 grounded answer context。
- 根据 YAML 选择 task type 和 answer layout。
- 让 LLM 基于 `question + rule_draft + grounded_context + evidence` 生成答案文本。
- 用 grounded rule answer 权威收口 claims、evidence refs 和 warnings。

## 输入

| 输入 | 来源 | 用途 |
|---|---|---|
| `question` | user/API | 提供用户原始问题，参与 task、layout、LLM prompt。 |
| `QueryPlan` | plan_compiler / plan_repair | 提供 intent、sub_tasks、constraints 等执行语义。 |
| `ToolResult[]` | executor，经 execution_validator 放行 | 答案事实唯一来源。 |
| `ExecutionDecision` | execution_policy | 提供 compiler/scenario 信息，辅助 query frame。 |
| `RouterOutput` | router / condition_normalizer | 提供 normalized conditions、scenario、context policy。 |
| `ResumeQAConfig` | graph state / `load_config()` | 读取 aggregator task、answer layout、LLM 配置。 |

## 输出

| 输出 | 写回字段 | 下游 |
|---|---|---|
| `AggregatedAnswer.answer` | `qa.answer.answer` | 给用户看的答案文本。 |
| `AggregatedAnswer.claims` | `qa.answer.claims` | `answer_validator` 校验 count/name/ranking/evidence。 |
| `AggregatedAnswer.used_evidence_refs` | `qa.answer.used_evidence_refs` | `answer_validator` 和 API trace 校验证据引用。 |
| `AggregatedAnswer.warnings` | `qa.answer.warnings` | 展示布局、空证据、LLM fallback 等 warning。 |
| aggregator meta | decision log / trace | 排查 task/layout/LLM/fallback/grounding。 |

## 主流程

```text
aggregate_answer_with_meta
-> prepare_answer_inputs
-> render_grounded_answer
-> run_fill_flow
-> _meta_from_flow
```

展开后：

```text
prepare_answer_inputs
  -> build_query_frame
  -> infer_answer_layout
  -> build_answer_context
  -> build_rule_draft
  -> build_prompt_payload

render_grounded_answer
  -> render_rule_answer
  -> grounded_authority

run_fill_flow
  -> fill_answer_with_llm
  -> reject_if_fact_drifted
  -> validate_layout_contract
  -> merge_grounding
```

## `render_grounded_answer` 的真实角色

`render_grounded_answer` 不是只有 fallback 才执行。

```text
每次 aggregator 都先执行 render_grounded_answer。
```

它有两个身份：

```text
1. fallback answer
   LLM 不可用、失败、事实漂移、布局违约时，直接使用 grounded rule answer。

2. grounding authority
   提供 claims / used_evidence_refs / warnings 的权威来源。
```

## LLM 成功时

LLM 根据 prompt payload 生成答案文本。

最终收口规则：

```text
answer = LLM answer text
claims = grounded claims
used_evidence_refs = grounded evidence refs
warnings = grounded warnings + LLM warnings
```

也就是说，LLM 可以组织语言、填充章节、解释结论，但不能改事实字段。

## LLM 失败或不合格时

如果出现以下情况：

```text
LLM disabled
LLM provider error
fact drift
layout contract violation
missing empty evidence disclaimer
ranking sequence changed
count changed
unknown candidate claim
```

最终回到：

```text
answer = grounded rule answer
claims = grounded claims
used_evidence_refs = grounded evidence refs
warnings = grounded warnings + fallback reason
```

## 它做什么

- 根据 YAML task rules 判断回答类型。
- 根据 YAML layout rules 选择回答框架。
- 从工具结果提取 count、candidate、profile、ranking、comparison、evidence。
- 构建 LLM payload。
- 允许 LLM 生成答案文本。
- 检查 LLM 是否事实漂移或违反 layout。
- 将 claims 和 evidence refs 收口到 grounded context。
- 写入 trace meta。

## 它不做什么

- 不调用工具。
- 不查数据库或向量库。
- 不重新规划。
- 不修复 `QueryPlan`。
- 不改变 count。
- 不重排 ranking。
- 不新增候选人、项目、公司、学校、技能、证据。
- 不决定 graph route。

## 示例

问题：

```text
金融候选人有几个，谁最强，依据是什么？
```

进入 aggregator 前，工具结果已经通过 `execution_validator`：

```text
count_candidates -> 3
rank_candidates -> [张三, 李四, 王五]
search_candidate_evidence -> EvidenceRef[]
```

aggregator 执行：

```text
1. build_query_frame
   task_type = candidate_decision_answer

2. infer_answer_layout
   layout = decision_chain

3. build_answer_context
   count = 3
   ranking = [张三, 李四, 王五]
   evidence = [...]

4. build_rule_draft
   sections = conclusion / count / ranking / key_reason / main_basis

5. build_prompt_payload
   question + rule_draft + grounded_context + selected_evidence + tool_results_summary

6. render_grounded_answer
   生成 fallback answer，并生成 grounded claims/evidence refs/warnings

7. run_fill_flow
   LLM 基于 payload 生成答案文本

8. merge_grounding
   保留 LLM answer 文本
   claims / used_evidence_refs / warnings 回到 grounded 权威来源
```

如果 LLM 把数量写成 4，或者把排序改成 `[李四, 张三, 王五]`，会被拒绝并回到 grounded rule answer。

## 文档阅读顺序

```text
1. README.md
2. AGGREGATOR_FLOW.md
3. YAML_USAGE.md
4. nodes/aggregator/node.py
5. core/answer_generation/generation.py
6. core/answer_generation/orchestration.py
7. core/answer_generation/task.py
8. core/answer_generation/layout.py
9. core/answer_generation/context.py
10. core/answer_generation/draft.py
11. core/answer_generation/prompt_payload.py
12. core/answer_generation/llm_flow.py
13. core/answer_generation/llm.py
14. core/answer_generation/renderers/router.py
```

## 验收命令

```bash
rg "Aggregator Node|AGGREGATOR_FLOW|YAML_USAGE|aggregate_answer_with_meta|prepare_answer_inputs|grounded_authority|merge_grounding" resume_query_ai_qa/nodes/aggregator resume_query_ai_qa/core/answer_generation
./.venv/bin/python -m compileall -q resume_query_ai_qa/nodes/aggregator resume_query_ai_qa/core/answer_generation
./.venv/bin/python resume_query_ai_qa/benchmarks/run_policy_contract_benchmark.py
./.venv/bin/python resume_query_ai_qa/benchmarks/run_plan_contract_benchmark.py
./.venv/bin/python resume_query_ai_qa/benchmarks/run_runtime_contract_benchmark.py
```
