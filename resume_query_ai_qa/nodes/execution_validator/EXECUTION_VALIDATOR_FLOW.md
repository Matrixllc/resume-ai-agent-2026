# Execution Validator Flow

这个文档按代码阅读顺序讲 `execution_validator`。

核心输入输出：

```text
QueryPlan + ToolResult[] + RouterOutput + session_context
-> ValidationResult
```

## 1. `validate_execution`

入口函数。

位置：

```text
execution.py
```

输入：

- `plan: QueryPlan`
- `tool_results: list[ToolResult]`
- `router_output: RouterOutput | None`
- `session_context: dict | None`
- `config: ResumeQAConfig | None`

输出：

- `ValidationResult`

主流程：

```text
failed tool classification
-> validate_required_tool_results
-> validate_evidence_coverage
-> validate_count_results
-> validate_compare_results
-> validate_empty_retrieval_results
-> validate_candidate_lineage
-> ValidationResult
```

如果有 errors：

```text
ValidationResult(ok=False, next_node="execution_repair")
```

如果没有 errors：

```text
ValidationResult(ok=True, next_node="aggregator")
```

注意：`next_node` 是默认建议，最终 route 还会结合 graph route 和 issue action。

## 2. `is_allowed_business_limit_result`

位置：

```text
execution_requirements.py
```

作用：

```text
判断 failed ToolResult 是不是允许的业务限制，而不是系统失败。
```

读取：

```text
tool_policy.yaml.business_limits
```

例子：

```yaml
profile_display_limit_exceeded:
  tool: get_candidate_profiles_intro
  error_code: profile_display_limit_exceeded
```

如果 `get_candidate_profiles_intro` 返回这个业务错误，validator 不把它当成普通 failed tool。

## 3. `validate_required_tool_results`

位置：

```text
execution_requirements.py
```

作用：

```text
根据 QueryPlan 的 intent，检查必需工具结果是否出现。
```

读取：

```text
tool_policy.yaml.intent_result_requirements
```

例子：

```yaml
candidate_ranking:
  all: [score_candidates_for_jd, rank_candidates]
```

如果 plan 里有 `candidate_ranking`，但 `tool_results` 里没有成功的 `rank_candidates`，就会产生错误：

```text
candidate_ranking requires rank_candidates result
```

## 4. `validate_evidence_coverage`

位置：

```text
core/rules/evidence_policy.py
```

作用：

```text
检查需要证据的 intent 是否拿到 EvidenceRef，以及每个候选人的证据数量是否足够。
```

读取：

```text
evidence_policy.yaml.intents
```

例子：

```yaml
candidate_compare_pair:
  requires_evidence: true
  min_evidence_per_candidate: 2
```

如果双人比较要求每人至少 2 条证据，但某个候选人只有 1 条，就会产生错误。

如果 `search_candidate_evidence` 正常返回但没有匹配 EvidenceRef，可能变成 warning，让 aggregator 说明“没有确认依据”。

## 5. `validate_count_results`

位置：

```text
execution_results.py
```

作用：

```text
检查 count_candidates 的数量是否等于前一个候选人集合的长度。
```

例子：

```text
filter_candidates -> [A, B, C]
count_candidates -> 2
```

错误：

```text
count_candidates returned 2, but candidate source has 3 items
```

这个检查保护的是“数量不能和候选人集合打架”。

## 6. `validate_compare_results`

位置：

```text
execution_results.py
```

作用：

```text
检查双人比较是否真的只返回两个人。
```

读取：

```text
validation.yaml.compare_pair.exact_candidate_count
```

当前默认：

```yaml
exact_candidate_count: 2
```

如果 `build_comparison_pack` 返回 1 个或 3 个候选人，就会产生错误。

## 7. `validate_empty_retrieval_results`

位置：

```text
execution_results.py
```

作用：

```text
判断 open_recall 场景下 filter_candidates 空结果是否需要触发 query fallback。
```

逻辑：

```text
如果 scenario 是 open_recall
并且没有 hybrid_search_candidates 成功结果
并且 filter_candidates 返回 []
-> 报 filter_candidates returned no candidates
```

后续 `execution_repair` 可以把它修成更开放的召回查询。

注意：hard_filter 空结果通常可以直接回答“没有找到”，不需要扩大召回。

## 8. `validate_candidate_lineage`

位置：

```text
execution_lineage.py
```

作用：

```text
检查 profile / ranking / evidence 是否跑出了 canonical candidate pool。
```

它会检查四类逃逸：

```text
canonical candidate_pool escaped session context
candidate_profile escaped resolved candidates
ranked_candidates escaped canonical candidate_pool
evidence_collection escaped candidate lineage
```

例子：

```text
filter_candidates -> [A, B, C]
rank_candidates -> [A, B, D]
```

错误：

```text
semantic: ranked_candidates escaped canonical candidate_pool: ['D']
```

## 9. `_canonical_candidate_ids`

位置：

```text
execution_lineage.py
```

作用：

```text
找出本轮执行的 canonical candidate pool。
```

优先来源：

```text
plan.artifact_bindings 里 artifact_type=candidate_collection 的 accepted_producer
```

如果没有 accepted producer，则退回到工具 role：

```text
config.tools_with_role("candidate_source")
```

并排除：

```text
resolve_candidate_reference
```

原因：

```text
resolve_candidate_reference 是上下文解析工具，不应该被当成新的候选人全集来源。
```

## 示例：count mismatch

工具结果：

```text
filter_candidates ok -> [A, B, C]
count_candidates ok -> 2
```

检查结果：

```text
validate_count_results
-> count_candidates returned 2, but candidate source has 3 items
-> ValidationResult(ok=False)
```

## 示例：open recall empty retrieval

场景：

```text
RouterOutput scenario = open_recall
```

工具结果：

```text
filter_candidates ok -> []
hybrid_search_candidates 没有执行
```

检查结果：

```text
validate_empty_retrieval_results
-> filter_candidates returned no candidates
-> 后续可进入 execution_repair query_fallback
```

## 示例：lineage escape

工具结果：

```text
filter_candidates ok -> [A, B, C]
search_candidate_evidence ok -> EvidenceRef(candidate_id=D)
```

检查结果：

```text
validate_candidate_lineage
-> semantic: evidence_collection escaped candidate lineage: ['D']
-> ValidationResult(ok=False)
```
