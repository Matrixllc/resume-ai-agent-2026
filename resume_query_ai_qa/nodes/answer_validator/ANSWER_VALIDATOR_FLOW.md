# Answer Validator Flow

## 阅读目标

这份文档只讲代码阅读线。`answer_validator` 的职责是把 `AggregatedAnswer` 和 `ToolResult[]` 对齐，判断最终答案是否能进入 `final`。

示例问题：

```text
金融候选人有几个，谁最强，依据是什么？
```

## 总入口

### `validate_answer(...)`

输入：

```text
answer: AggregatedAnswer
tool_results: ToolResult[]
plan: QueryPlan | None
config: ResumeQAConfig | None
```

输出：

```text
ValidationResult
```

执行顺序：

```text
validate_claim_support
-> validate_answer_count
-> validate_answer_names
-> validate_answer_ranking
-> validate_answer_evidence_refs
-> validate_answer_contact
-> validate_answer_layout
-> validate_required_structured_claims
-> validate_evidence_coverage
-> ValidationResult
```

为什么这样做：

```text
先校验事实来源
再校验数量/姓名/排序/证据这些硬事实
再校验隐私和布局
最后校验证据覆盖
```

## 1. Claim Support

### `validate_claim_support(answer, tool_results)`

做什么：

```text
检查每个非 other claim 是否有 supported_by
检查 supported_by 是否指向本轮成功执行过的 tool_name
```

例子：

```text
claim.supported_by = ["rank_candidates"]
tool_results 里存在 ok=True 的 rank_candidates
-> 通过
```

如果 claim 写了不存在的工具：

```text
claim.supported_by = ["fake_tool"]
-> unknown_tool_support
```

## 2. Count

### `validate_answer_count(answer, tool_results, config)`

数据来源：

```text
count_candidates tool result
answer.claims[type=count]
answer.answer 文本
validation.yaml.answer.count_subject_terms
```

执行过程：

```text
1. 从 tool_results 取最后一个成功的 count_candidates 结果。
2. 检查 count claim.value 是否等于工具数量。
3. 如果 claim.value 没有，就扫 claim.text 里的数字。
4. 再扫 answer.answer 里的数字。
5. 只有 answer.answer 同时出现 count_subject_terms 时，才把数字不一致视为 count 文本错误。
```

例子：

```text
tool count = 3
answer.claims: count.value = 3
answer.answer: "金融候选人共有 3 位"
-> 通过
```

如果答案写：

```text
"金融候选人共有 5 位"
-> answer_count_text_mismatch
```

## 3. Candidate Names

### `validate_answer_names(answer, tool_results)`

数据来源：

```text
candidate_names_from_results(tool_results)
answer.claims[type=name/profile]
```

做什么：

```text
检查答案 claims 中的候选人名是否来自本轮工具结果。
```

注意：

```text
这里主要检查 structured claims。
它不是完整扫描 answer.answer 文本中的所有人名。
```

## 4. Ranking

### `validate_answer_ranking(answer, tool_results, config, plan)`

数据来源：

```text
rank_candidates tool result
answer.claims[type=ranking]
answer.answer 文本
plan.constraints.ranking_output_limit
validation.yaml.answer.ranking_segment_markers
```

执行过程：

```text
1. 从 tool_results 取 rank_candidates 结果。
2. 如果 plan 限定 TopK，只校验 TopK 范围。
3. 检查 ranking claims：
   - subject 是否在 rank_candidates 名单里
   - rank 是否一致
   - score 是否一致
   - claims 顺序是否一致
4. 再检查 answer.answer 文本中候选人出现顺序是否符合排名。
5. 如果文本有“排序结果/排名/排序/从高到低/推荐顺序”，从该段开始扫；否则扫全文。
```

例子：

```text
rank_candidates:
1. 张三
2. 李四

answer.answer:
"排序结果：张三第一，李四第二。"
-> 通过
```

如果答案写：

```text
"排序结果：李四第一，张三第二。"
-> ranking_answer_order_mismatch
```

## 5. Evidence Refs

### `validate_answer_evidence_refs(answer, tool_results)`

数据来源：

```text
available_evidence_ids(tool_results)
answer.used_evidence_refs
answer.claims[].evidence_ids
```

做什么：

```text
检查 answer 使用的 evidence_id 是否存在于本轮工具结果。
```

例子：

```text
tool_results 只有 evidence_id=e1/e2
answer.used_evidence_refs = [e3]
-> unknown_evidence_ref
```

## 6. Privacy

### `validate_answer_contact(answer, tool_results, config)`

数据来源：

```text
answer.answer 文本
validation.yaml.privacy
get_candidate_profile_intro.contact_hidden
```

执行过程：

```text
1. 如果 YAML 关闭 hide_contact_by_default，跳过。
2. 如果 profile 工具明确允许展示 contact，跳过。
3. 扫 email。
4. 扫 phone-like 文本，但会先去掉日期范围，减少误判。
5. 扫 wechat alias。
6. 扫 sensitive_attributes alias。
```

这一步直接扫最终文本，所以能拦住 LLM 文本里的联系方式泄露。

## 7. Layout

### `validate_answer_layout(answer, config)`

数据来源：

```text
answer.warnings 中的 answer_layout:<layout>
answer_layouts.yaml.layouts.<layout>
answer.answer 文本
```

执行过程：

```text
1. 从 answer.warnings 找 answer_layout:<layout>。
2. 到 answer_layouts.yaml.layouts 读取 layout 配置。
3. 调用 layout_contract / validate_layout_contract。
4. 检查 required_title_sections 和 first_section。
5. candidate_blocks 有额外检查：
   - 必须有主要依据
   - 必须有个人信息
   - 必须有经历核查
   - 主要依据不能跑到候选人块前面
```

例子：

```text
answer.warnings = ["answer_layout:decision_chain"]
answer_layouts.yaml.decision_chain.first_section = conclusion
titles.conclusion = "结论"

answer.answer 必须以“结论”开头。
```

## 8. Required Structured Claims

### `validate_required_structured_claims(answer, tool_results, plan)`

数据来源：

```text
tool_results
plan intent calls
answer.claims
```

做什么：

```text
如果工具结果里有 count_candidates，答案必须有 count claim。
如果 plan 包含 candidate_list，答案必须有 name claims。
如果工具结果里有 rank_candidates，答案必须有 ranking claims。
如果工具结果里有 build_comparison_pack，答案必须有 comparison claims。
```

为什么要有这一步：

```text
即使 answer.answer 文本看起来写了内容，系统也要求保留结构化 claims，
方便 validator 和后续 diagnosis 稳定检查。
```

## 9. Evidence Coverage

### `validate_evidence_coverage(plan, tool_results, config)`

来源：

```text
core.rules.evidence_policy
evidence_policy.yaml
tool_results
plan
```

做什么：

```text
判断本轮是否缺少应该有的证据。
```

特别规则：

```text
如果 answer.used_evidence_refs 非空，evidence_errors 会变成阻断错误。
如果只是 evidence_warnings，会作为 warning 返回，不一定阻断 final。
```

## 最终返回

如果有 errors：

```text
ValidationResult(
  ok=False,
  next_node="answer_rewrite",
  repair_hint="Rewrite the answer using only claims supported by tool_results."
)
```

如果没有 errors：

```text
ValidationResult(
  ok=True,
  next_node="final"
)
```

## 当前保留的复杂点

`answer_validator` 当前不是完整的 LLM 文本事实核验器。

它做了：

```text
claims / evidence refs 的工具事实校验
count / ranking / privacy / layout 的 answer 文本扫描
```

它没做：

```text
把 answer.answer 每句话抽成事实，再逐条和 tool_results 对齐
```

后续如果要加强，可以新增独立的 `answer_text_grounding_validator`，不要把这类复杂逻辑塞进现有 claim/layout/privacy 文件里。
