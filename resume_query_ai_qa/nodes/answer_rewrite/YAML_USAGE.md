# Answer Rewrite YAML Usage

## 这份文档看什么

这份文档是 `answer_rewrite` 的 YAML 字段地图。它不讲完整流程，只说明哪些配置会影响 rewrite policy、rewrite prompt、layout 检查和后续复检。

`answer_rewrite` 直接读取很少，主要直接使用：

```text
validation.yaml.answer_repair.rule_repair_categories
```

其他 YAML 多数由 `core.answer_generation` 或后续 `answer_validator` 间接使用。

## validation.yaml.answer_repair

路径：

```text
resume_query_ai_qa/configs/validation.yaml
```

字段：

```yaml
answer_repair:
  rule_repair_categories:
    - count
    - name
    - ranking
    - evidence_id
    - required_claim
    - layout
    - privacy
    - evidence_coverage
```

谁用：

```text
answer_rewrite.policy.classify_answer_repair_policy
```

做什么：

```text
如果所有 hard ValidationIssue.category 都在这个列表里，
policy 返回 action=rule_repair。
```

注意：

```text
这里的 rule_repair 不是在 answer_rewrite 内部重建答案。
它表示“这个错误适合丢弃当前答案，交给 rule_answer_fallback 做确定性兜底”。
```

例子：

```text
answer_validator errors:
  category=count
  category=ranking

rule_repair_categories 包含 count/ranking
-> action=rule_repair
-> answer_rewrite 返回 answer=None + fallback_request
-> graph route 到 rule_answer_fallback
```

如果出现不在列表里的 category：

```text
category=expression
-> action=llm_rewrite
-> 尝试生成 rewrite candidate
```

## validation.yaml.retry_limits

字段：

```yaml
retry_limits:
  aggregator_rewrite: 1
```

当前关系：

```text
graph runner 的 max_answer_rewrites 默认值是 1。
validation.yaml.retry_limits.aggregator_rewrite 是配置合同和诊断参考。
```

谁实际控制 graph 次数：

```text
graph.runner.run(max_answer_rewrites=1)
graph.routes.route_after_answer_validation
```

也就是说：

```text
answer_rewrite 节点本身不读取 retry_limits。
rewrite 次数由 graph state 里的 max_answer_rewrites 控制。
```

## answer_layouts.yaml.layouts

路径：

```text
resume_query_ai_qa/configs/answer_layouts.yaml
```

间接使用位置：

```text
core.answer_generation.prepare_answer_inputs
core.answer_generation.run_rewrite_flow
answer_validator.validate_answer_layout
```

在 rewrite 中的作用：

```text
1. prepare_answer_inputs 会重新推导 layout 和 rule_draft。
2. build_rewrite_prompt 会把 layout 要求放进 prompt。
3. run_rewrite_flow 会用 validate_layout_contract 拒绝 layout 违约的 LLM 输出。
4. rewrite 后回到 answer_validator，再按 YAML layout 复检最终答案。
```

例子：

```text
layout=decision_chain
required_title_sections=[conclusion,count,ranking,key_reason,main_basis]
first_section=conclusion

LLM rewrite 如果没有从“结论”开始，可能被 layout_contract 拒绝。
```

## aggregator_tasks.yaml.task_types

间接使用位置：

```text
core.answer_generation.prepare_answer_inputs
build_query_frame
infer_answer_layout
build_rule_draft
build_prompt_payload
```

在 rewrite 中的作用：

```text
rewrite 会复用 aggregator 的 answer framework。
也就是根据 QueryPlan / ToolResult / task type 重新构建 query_frame 和 rule_draft，
让 LLM rewrite 仍然按同一套回答框架修。
```

## validation.yaml.answer / privacy

字段示例：

```yaml
answer:
  count_subject_terms: [候选人, 共有, 总数, 位, 个]
  ranking_segment_markers: [排序结果, 排名, 排序, 从高到低, 推荐顺序]

privacy:
  hide_contact_by_default: true
  contact_aliases:
    wechat: [微信, wechat]
  sensitive_attributes:
    - age
    - gender
```

关系：

```text
answer_rewrite 不直接读取这些字段。
rewrite 后必须回 answer_validator，由 answer_validator 用这些字段复检最终文本。
```

为什么仍然和 rewrite 有关：

```text
如果 rewrite 后的 answer.answer 仍然数量错误、排序错误、泄露隐私或 layout 违约，
answer_validator 会再次拦截。
```

## evidence_policy.yaml

间接使用位置：

```text
answer_validator.validate_evidence_coverage
core.answer_generation.prepare_answer_inputs / context
```

在 rewrite 中的作用：

```text
rewrite prompt 和 grounded_context 会携带 evidence 状态。
如果 evidence 为空，LLM rewrite 必须表达证据不足，而不是强行确认。
```

最终仍由：

```text
answer_validator
```

复检证据覆盖和空证据表达。

## 快速区分

| YAML | answer_rewrite 怎么用 |
| --- | --- |
| `validation.yaml.answer_repair.rule_repair_categories` | 直接读取，决定 rule fallback 还是 LLM rewrite。 |
| `validation.yaml.retry_limits.aggregator_rewrite` | 配置合同/诊断参考；实际次数由 graph runner state 控制。 |
| `answer_layouts.yaml.layouts` | 间接用于 rule_draft、prompt、layout rejection、validator 复检。 |
| `aggregator_tasks.yaml.task_types` | 间接用于 query_frame、layout 和 answer framework。 |
| `validation.yaml.answer` | rewrite 后由 answer_validator 复检 count/ranking 文本。 |
| `validation.yaml.privacy` | rewrite 后由 answer_validator 复检隐私泄露。 |
| `evidence_policy.yaml` | 间接影响 empty evidence 表达和证据覆盖复检。 |

## 当前边界

`answer_rewrite` 的 YAML 使用是“轻入口、重复检”：

```text
入口 policy 只读 answer_repair.rule_repair_categories
生成候选答案时复用 aggregator 的 YAML-driven answer framework
最终安全性由 answer_validator 再读 validation/evidence/layout YAML 复检
```
