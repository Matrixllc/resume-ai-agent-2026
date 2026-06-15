# Aggregator YAML Usage

aggregator 的 YAML 使用目标是：决定“答案类型”和“回答框架”，并把这些框架交给 LLM / rule renderer 生成 `AggregatedAnswer`。

核心配置：

```text
aggregator_tasks.yaml = 先判断这是什么回答任务
answer_layouts.yaml = 再判断用什么回答布局
```

## 直接使用

### `aggregator_tasks.yaml.task_types`

使用位置：

```text
core/answer_generation/task.py
-> classify_task_type()
```

作用：

```text
根据 intents / scenarios / successful_tools / trigger terms 判断 task_type。
```

例子：

```yaml
candidate_decision_answer:
  priority: 75
  intents_any: [candidate_ranking, jd_scoring]
  required_tools:
    any: [rank_candidates, score_candidates_for_jd]
  freedom_level: strict
  default_layout: decision_chain
```

含义：

```text
如果本轮 intent 是 candidate_ranking / jd_scoring，
并且工具结果里有 rank_candidates 或 score_candidates_for_jd，
就可以匹配 candidate_decision_answer。
```

输出会进入 `query_frame`：

```text
task_type
freedom_level
default_layout
matched_rule
match_reason
```

### `aggregator_tasks.yaml.generation_contract`

使用方式：

```text
定义 aggregator 允许的 generation mode。
```

当前模式包括：

```text
rule_grounded_renderer
llm_fill
llm_fill_rejected
rule_fallback_after_llm_error
```

这些 mode 会出现在 trace meta 中，用于说明本轮答案是 LLM 生成、规则生成，还是 LLM 被拒绝后回落。

### `answer_layouts.yaml.layouts`

使用位置：

```text
core/answer_generation/layout.py
-> infer_answer_layout()
```

作用：

```text
根据 task_type / freedom_level / successful_tools / trigger terms 选择 answer layout。
```

例子：

```yaml
decision_chain:
  task_types:
    - candidate_decision_answer
  freedom_levels:
    - strict
  required_tools:
    all:
      - count_candidates
      - rank_candidates
```

含义：

```text
candidate_decision_answer 且工具结果里有 count_candidates + rank_candidates，
就可以选择 decision_chain 布局。
```

### `answer_layouts.yaml.sections`

使用位置：

```text
draft.py -> build_rule_draft()
llm.py -> build_layout_prompt_requirements()
renderers/*
```

作用：

```text
定义答案应该包含哪些语义段落。
```

例子：

```yaml
sections:
  - conclusion
  - count
  - ranking
  - key_reason
  - main_basis
```

### `answer_layouts.yaml.required_sections`

作用：

```text
定义必须回答的语义内容。
```

注意：

```text
required_sections 不等于必须显示标题。
```

它表示语义上必须覆盖这些内容。

### `answer_layouts.yaml.required_title_sections`

作用：

```text
定义哪些章节标题必须在最终 answer 文本中原样显示。
```

例子：

```yaml
required_title_sections: [conclusion, count, ranking, key_reason, main_basis]
titles:
  conclusion: "结论"
  count: "候选人总数"
```

含义：

```text
如果 required_title_sections 包含 count，
最终答案必须出现标题 “候选人总数”。
```

### `answer_layouts.yaml.hard_constraints`

使用位置：

```text
draft.py -> build_rule_draft()
llm.py -> build_fill_prompt()
answer_validator 也会间接检查部分合同
```

作用：

```text
给 LLM 和规则渲染器提供不可违反的硬约束。
```

例子：

```yaml
hard_constraints:
  - "不能改变 count_candidates 的数量。"
  - "不能改变 rank_candidates 的排序、分数或候选人姓名。"
```

### `answer_layouts.yaml.claim_contract`

作用：

```text
声明该 layout 需要哪些 claim 类型，以及 claim 应该来自哪些 context。
```

例子：

```yaml
claim_contract:
  required_claim_types: [count, ranking]
  ranking_from_context: true
```

aggregator 会生成 grounded claims；answer_validator 会继续验证 claim 是否满足合同。

## 间接相关

### `validation.yaml.answer`

主要使用者：

```text
answer_validator
```

作用：

```text
定义最终答案不能改 count、不能改 ranking、不能暴露联系方式等。
```

aggregator 不直接用它做主要生成，但 aggregator 的设计要配合这些校验：

```text
claims / evidence refs 回到 grounded context
LLM answer 文本做 fact drift 检查
```

### `evidence_policy.yaml`

主要使用者：

```text
execution_validator
answer_validator
answer generation grounding
```

对 aggregator 的影响：

```text
如果 evidence 为空，context.empty_flags 会带上 evidence.empty。
grounded_authority 会写入 empty evidence warning。
LLM 输出必须说明不能确认，不能把空证据写成有证据。
```

## LLM Payload 和 YAML 的关系

`build_prompt_payload()` 会把 YAML 框架和工具事实一起交给 LLM：

```text
question
query_frame              # 来自 aggregator_tasks.yaml 匹配结果
rule_draft               # 来自 answer_layouts.yaml
grounded_context         # 来自 ToolResult[]
selected_evidence        # 来自 ToolResult[] 中的 EvidenceRef
tool_results_summary     # 工具结果摘要
```

所以 LLM 看到的不是纯文本问题，而是：

```text
用户 query + YAML 回答框架 + 工具事实 + evidence
```

## 小结

aggregator 的 YAML 心智模型：

```text
aggregator_tasks.yaml:
  决定本轮是什么回答任务

answer_layouts.yaml:
  决定答案怎么组织、哪些标题必须出现、有哪些硬约束

validation.yaml.answer:
  下游 answer_validator 的最终答案合同

evidence_policy.yaml:
  影响证据不足和 empty evidence 表达
```

重要边界：

```text
YAML 决定框架和合同
ToolResult 决定事实
LLM 生成 answer 文本
grounding 决定 claims / evidence refs / warnings
```
