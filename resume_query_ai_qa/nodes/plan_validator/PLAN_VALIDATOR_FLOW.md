# Plan Validator Flow

这份文档只讲代码阅读线。YAML 字段地图看 `YAML_USAGE.md`，节点总览看 `README.md`。

## 阅读入口

```text
plan.py
-> plan_structure.py
-> plan_boundaries.py
-> plan_artifacts.py
-> plan_semantics.py
```

## 1. validate_plan

位置：

```text
nodes/plan_validator/plan.py
```

输入：

- `plan`
- `config`
- `router_output`
- `session_context`

输出：

- `ValidationResult`

执行顺序：

```text
validate_plan_structure
-> validate_compare_boundaries
-> validate_ranking_boundaries
-> validate_count_boundaries
-> validate_artifact_source_contract
-> validate_plan_semantics
-> ValidationResult
```

## 2. validate_plan_structure

位置：

```text
plan_structure.py
```

职责：

```text
检查 QueryPlan 的基础结构和工具协议。
```

检查内容：

```text
compound 的跨子任务依赖
out_of_scope 不能调用简历工具
router scenario contract
tool allowed / forbidden
tool arguments
depends_on / output_key / $ref
```

## 3. validate_tool_dependencies

位置：

```text
plan_structure.py
```

职责：

```text
检查工具调用顺序和引用关系。
```

关键规则：

```text
depends_on 必须引用已经出现过的 output_key
$ref 必须引用已经出现过的 output_key
$ref 对应 root 必须出现在 depends_on
output_key 不能重复，除非 compound 跨任务允许
```

例子：

```text
score_candidates_for_jd.candidate_ids = $candidate_pool
```

那么：

```text
candidate_pool 必须是前面某个工具的 output_key
depends_on 必须包含 candidate_pool
```

## 4. validate_tool_arguments

位置：

```text
plan_structure.py
```

职责：

```text
用 tool registry 的函数签名检查 ToolCallSpec.arguments。
```

检查：

```text
工具是否存在
是否传了不支持的参数
是否缺少必填参数
```

## 5. validate_router_scenario_contract

位置：

```text
plan_structure.py
```

职责：

```text
检查 RouterOutput.scenario_decisions 是否符合 scenarios.yaml。
```

检查：

```text
每个 intent 都有 scenario
scenario 名称存在
scenario 允许该 intent
没有多余 intent 的 scenario decision
```

## 6. validate_compare_boundaries

位置：

```text
plan_boundaries.py
```

职责：

```text
candidate_compare_pair 必须限定刚好两个候选人。
```

允许：

```text
candidate_ids 是 $ref / structured ref
```

否则会直接数候选人数量。

## 7. validate_ranking_boundaries

位置：

```text
plan_boundaries.py
```

职责：

```text
candidate_ranking 必须有评分标准、评分工具、排序工具。
```

典型要求：

```text
criteria_source
score_candidates_for_jd
rank_candidates
```

## 8. validate_count_boundaries

位置：

```text
plan_boundaries.py
```

职责：

```text
candidate_count 必须有候选人来源，并且必须调用 count_candidates。
```

## 9. validate_artifact_source_contract

位置：

```text
plan_artifacts.py
```

职责：

```text
检查候选人集合和后续消费链是否来自正确产物。
```

重点检查：

```text
candidate_collection 只能有一个 canonical binding
canonical producer 必须真的在 plan 里
filtered scope 不能来自 list_all_candidates
hard domain 不能只靠 query-only hybrid_search_candidates
count_candidates 必须消费 canonical candidate_collection
score_candidates_for_jd 必须消费 canonical/resolved candidate source
search_candidate_evidence 必须消费 canonical/resolved/ranked candidates
workflow artifact_contracts 必须满足
```

## 10. validate_plan_semantics

位置：

```text
plan_semantics.py
```

职责：

```text
检查 QueryPlan 是否满足 RouterOutput 的语义合同。
```

重点检查：

```text
out_of_scope 不执行工具
compound 包含所有 sub_intents
candidate_ranking 有 criteria/score/rank
candidate_filter 不能空筛选
hard domain/skill/concept 必须进入 filter_candidates 结构化参数
context_policy 要求的上下文必须存在
context candidate_ids 必须限制到计划
requires_evidence 必须有 evidence-capable tool
```

## 11. ValidationResult

位置：

```text
core/schemas.py
```

通过：

```python
ValidationResult(
    ok=True,
    next_node="executor",
)
```

失败：

```python
ValidationResult(
    ok=False,
    errors=[...],
    error_details=validation_issues(errors, "plan"),
    repair_hint="Rewrite the plan using only allowed tools and required boundary steps.",
    next_node="plan_repair",
)
```

## 示例

问题：

```text
金融候选人有几个，谁最强，依据是什么？
```

如果 plan 有：

```text
filter_candidates(domains_any=["金融"]) -> candidate_pool
count_candidates($candidate_pool)
score_candidates_for_jd($candidate_pool, $criteria)
rank_candidates($scores)
search_candidate_evidence($ranked_candidates)
```

validator 会确认：

```text
domain=金融 确实进入 filter_candidates
count/ranking/evidence 工具链完整
$candidate_pool/$criteria/$scores/$ranked_candidates 都引用了已有 output_key
evidence 消费 ranked_candidates
```

如果缺少：

```text
filter_candidates(domains_any=["金融"])
```

而用：

```text
list_all_candidates -> count_candidates
```

则会报：

```text
semantic: filtered candidate scope cannot be produced by all-scope source list_all_candidates
```
