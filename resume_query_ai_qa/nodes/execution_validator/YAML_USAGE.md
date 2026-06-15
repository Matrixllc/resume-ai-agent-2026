# Execution Validator YAML Usage

`execution_validator` 的 YAML 使用目标是：把工具执行结果和配置合同对齐。

它不像 executor 只看 retry，也不像 plan_validator 看执行前计划合法性。它看的是：

```text
ToolResult[] 是否满足 intent / evidence / compare / lineage 合同
```

## 直接使用

### `tool_policy.yaml.business_limits`

使用位置：

```text
execution_requirements.py -> is_allowed_business_limit_result()
```

作用：

```text
把某些 failed ToolResult 识别为允许的业务限制，而不是系统失败。
```

例子：

```yaml
business_limits:
  profile_display_limit_exceeded:
    tool: get_candidate_profiles_intro
    error_code: profile_display_limit_exceeded
```

含义：

```text
get_candidate_profiles_intro 如果因为展示数量上限失败，可以作为业务限制结果保留。
```

### `tool_policy.yaml.intent_result_requirements`

使用位置：

```text
execution_requirements.py -> validate_required_tool_results()
```

作用：

```text
定义每个 intent 执行后必须看到哪些工具结果。
```

例子：

```yaml
intent_result_requirements:
  candidate_count:
    all: [count_candidates]
  candidate_ranking:
    all: [score_candidates_for_jd, rank_candidates]
  candidate_profile_intro:
    any: [get_candidate_profile_intro, get_candidate_profiles_intro]
```

含义：

```text
all = 所有工具结果都必须出现
any = 至少出现一个工具结果
```

### `validation.yaml.compare_pair`

使用位置：

```text
execution_results.py -> validate_compare_results()
```

作用：

```text
定义双人比较的候选人数合同。
```

例子：

```yaml
compare_pair:
  exact_candidate_count: 2
```

含义：

```text
build_comparison_pack 必须返回 2 个候选人。
```

## 通过 helper 间接使用

### `evidence_policy.yaml.intents`

间接使用位置：

```text
execution.py -> validate_evidence_coverage()
core/rules/evidence_policy.py
```

作用：

```text
定义哪些 intent 需要证据，以及每个候选人最低需要多少 EvidenceRef。
```

例子：

```yaml
candidate_compare_pair:
  requires_evidence: true
  min_evidence_per_candidate: 2

candidate_ranking:
  requires_evidence: true
  min_evidence_per_candidate: 1
```

含义：

```text
双人比较每人至少 2 条证据
排名每个需要覆盖的候选人至少 1 条证据
```

### `tool_policy.yaml.tools.*.roles`

间接使用位置：

```text
execution_lineage.py -> _canonical_candidate_ids()
config.tools_with_role("candidate_source")
```

作用：

```text
识别哪些工具可以作为 canonical candidate pool 的来源。
```

lineage 检查会用它判断：

```text
ranking / profile / evidence 是否跑出了候选人来源集合
```

### `validation.yaml.issue_actions`

使用位置：

```text
execution_validator 产出 ValidationResult.error_details
graph route / execution_repair 再根据 issue_actions 路由
```

作用：

```text
决定执行校验失败后是 repair / clarify / fail。
```

注意：

```text
execution_validator 本身不直接决定最终 route。
它只把错误转成结构化 ValidationIssue。
```

## 输入对象里的配置结果

### `QueryPlan.artifact_bindings`

来源：

```text
plan_compiler / plan_repair
```

作用：

```text
告诉 lineage 检查哪个工具产物是 canonical candidate_collection。
```

例子：

```text
artifact_type = candidate_collection
accepted_producer = filter_candidates
```

含义：

```text
filter_candidates 的结果是本轮候选人集合的权威来源。
ranking / evidence / profile 不能跑出这个集合。
```

### `RouterOutput.scenario_decisions`

来源：

```text
router / finalizer
```

作用：

```text
帮助 validate_empty_retrieval_results 判断当前 intent 是否是 open_recall。
```

open_recall 空结果可以进入 query fallback；hard_filter 空结果通常可以直接回答“没有找到”。

## 小结

execution_validator 的 YAML 心智模型：

```text
tool_policy.yaml:
  哪些 failed result 是允许的业务限制
  每个 intent 必须有哪些工具结果
  哪些工具是 candidate_source

evidence_policy.yaml:
  哪些 intent 需要证据
  每个候选人最低证据数量

validation.yaml:
  compare_pair 人数合同
  issue_actions 后续路由策略

QueryPlan / RouterOutput:
  提供本次执行的 intent、scenario、artifact binding、candidate lineage 上下文
```
