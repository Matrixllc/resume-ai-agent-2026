# Answer Validator YAML Usage

## 这份文档看什么

这份文档是 `answer_validator` 的 YAML 字段地图。它不讲完整执行流程，只说明哪些配置会影响答案出口校验。

`answer_validator` 主要读取：

```text
validation.yaml.answer
validation.yaml.privacy
answer_layouts.yaml.layouts
evidence_policy.yaml
```

还有一些字段不是本节点直接读，但会影响 route / rewrite / fallback。

## validation.yaml.answer

路径：

```text
resume_query_ai_qa/configs/validation.yaml
```

直接使用字段：

```yaml
answer:
  count_subject_terms: [候选人, 共有, 总数, 位, 个]
  ranking_segment_markers: [排序结果, 排名, 排序, 从高到低, 推荐顺序]
```

### `count_subject_terms`

谁用：

```text
answer_claims.validate_answer_count
```

做什么：

```text
当 answer.answer 里出现数字时，不是所有数字都按候选人数处理。
只有文本同时出现“候选人/共有/总数/位/个”等词，才认为这个数字可能在表达 count。
```

例子：

```text
tool count = 3
answer.answer = "金融候选人共有 5 位"
-> 出现 “候选人/共有/位”，所以数字 5 会被当成 count 检查
-> answer_count_text_mismatch
```

### `ranking_segment_markers`

谁用：

```text
answer_claims.validate_answer_ranking
```

做什么：

```text
如果答案里有“排序结果/排名/排序/从高到低/推荐顺序”，validator 从这些词开始找 ranking 段。
如果没有这些词，就扫全文里的候选人出现顺序。
```

例子：

```text
rank_candidates = [张三, 李四]
answer.answer = "排序结果：李四第一，张三第二"
-> ranking_answer_order_mismatch
```

## validation.yaml.privacy

直接使用字段：

```yaml
privacy:
  hide_contact_by_default: true
  contact_aliases:
    wechat: [微信, wechat]
  sensitive_attributes:
    - age
    - gender
    - ethnicity
    - marital_status
    - fertility_status
    - political_identity
    - photo
  sensitive_attribute_aliases:
    age: [年龄, 岁]
    gender: [性别, 男, 女]
```

谁用：

```text
answer_privacy.validate_answer_contact
```

做什么：

```text
默认不允许输出 email / phone / wechat / sensitive attributes。
如果 get_candidate_profile_intro 明确返回 contact_hidden=false 且有 contact，才允许展示联系方式。
```

注意：

```text
这一步直接扫描 answer.answer 文本。
它是 answer_validator 中少数会直接拦截 LLM 文本泄露的检查。
```

## answer_layouts.yaml.layouts

路径：

```text
resume_query_ai_qa/configs/answer_layouts.yaml
```

直接使用字段：

```yaml
layouts:
  decision_chain:
    required_title_sections: [conclusion, count, ranking, key_reason, main_basis]
    first_section: conclusion
    titles:
      conclusion: "结论"
      count: "候选人总数"
      ranking: "排序结果"
      key_reason: "关键理由"
      main_basis: "主要依据"
```

谁用：

```text
answer_layout.validate_answer_layout
```

layout 名从哪里来：

```text
answer.warnings 里的 answer_layout:<layout>
```

执行过程：

```text
answer.warnings = ["answer_layout:decision_chain"]
-> 读取 answer_layouts.yaml.layouts.decision_chain
-> 检查 required_title_sections
-> 检查 first_section
-> 检查 titles
```

### `required_title_sections`

含义：

```text
这些 section 对应的可见标题必须出现在 answer.answer 中。
```

### `first_section`

含义：

```text
答案开头必须是这个 section 对应的标题。
```

例子：

```text
first_section = conclusion
titles.conclusion = "结论"

answer.answer 必须从 “结论” 开始。
```

### `titles`

含义：

```text
section key 到中文标题的映射。
validator 检查的是最终文本里的中文标题，不是 section key。
```

## answer_layouts.yaml.claim_contract

字段示例：

```yaml
claim_contract:
  required_claim_types: [count, ranking]
  ranking_from_context: true
```

当前关系：

```text
answer_validator 的 required structured claims 主要由 tool_results + plan 推导。
claim_contract 更多是 aggregator / answer layout 生成阶段的约束说明。
```

换句话说：

```text
claim_contract 会影响答案应该长什么样；
answer_validator 当前不是逐字段直接解释所有 claim_contract。
```

## evidence_policy.yaml

谁用：

```text
core.rules.evidence_policy.validate_evidence_coverage
answer.py 间接调用
```

做什么：

```text
校验本轮 plan 需要证据时，tool_results 是否提供了足够证据。
```

在 `answer_validator` 中的处理：

```text
evidence_warnings -> ValidationResult.warnings
evidence_errors -> 只有 answer.used_evidence_refs 非空时才加入阻断 errors
```

这个策略让系统能区分：

```text
工具正常返回空证据，并且答案表达了证据不足
vs
答案引用了不存在或不充分的证据
```

## validation.yaml.answer_repair

字段：

```yaml
answer_repair:
  rule_repair_categories: [count, name, ranking, evidence_id, required_claim, layout, privacy, evidence_coverage]
```

当前关系：

```text
answer_validator 产出 ValidationIssue.category。
后续 answer_rewrite / route 可以根据这些 category 判断能否 rule repair。
```

也就是说，这个字段主要给下游 repair/route 使用，不是 `answer_validator` 内部每个函数直接读取。

## validation.yaml.issue_actions

当前关系：

```text
主要给 graph route / repair / fail 策略使用。
answer_validator 自己只返回 ValidationResult，不直接执行 issue_actions。
```

## 快速区分

| YAML | 本节点怎么用 |
| --- | --- |
| `validation.yaml.answer.count_subject_terms` | 扫 answer.answer 里的 count 文本。 |
| `validation.yaml.answer.ranking_segment_markers` | 定位 answer.answer 里的 ranking 段。 |
| `validation.yaml.privacy` | 扫联系方式和敏感属性。 |
| `answer_layouts.yaml.layouts.*` | 校验最终答案标题、首段和特殊布局。 |
| `answer_layouts.yaml.claim_contract` | 主要影响生成阶段，本节点不完整解释。 |
| `evidence_policy.yaml` | 间接校验证据覆盖。 |
| `validation.yaml.answer_repair` | 下游 rewrite/fallback 路由参考。 |
| `validation.yaml.issue_actions` | graph route 策略参考。 |
