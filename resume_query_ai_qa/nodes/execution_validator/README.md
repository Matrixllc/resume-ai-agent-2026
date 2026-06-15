# Execution Validator Node

一句话：`execution_validator` 检查 executor 产出的 `ToolResult[]` 是否满足 `QueryPlan` 和 `RouterOutput` 的执行合同。

## 架构位置

```text
executor
-> execution_validator
-> aggregator / execution_repair / clarification / fail
```

前后节点边界：

```text
executor = 调用工具并返回 ToolResult[]
execution_validator = 检查 ToolResult[] 是否足够、是否一致、是否越界
execution_repair = 修复可修复的执行结果问题
aggregator = 只消费验证通过的工具事实
```

executor 不抛异常中断整条链，而是把失败包装成 `ToolResult`。`execution_validator` 再把这些结果转成 `ValidationResult`，供 graph route 判断下一步。

## 节点目标

`execution_validator` 做五类检查：

- `tool failure`：是否有 failed `ToolResult`。
- `required results`：当前 intent 必须有的工具结果是否齐全。
- `evidence coverage`：需要证据的 intent 是否拿到了足够 EvidenceRef。
- `result consistency`：count / compare / empty retrieval 等结果是否自洽。
- `candidate lineage`：profile / ranking / evidence 是否跑出了 canonical candidate pool。

## 输入

| 输入 | 来源 | 用途 |
|---|---|---|
| `QueryPlan` | `plan_compiler` / `plan_repair` | 判断当前 intent、工具调用、artifact binding 和候选人来源。 |
| `ToolResult[]` | `executor` | 检查工具状态、工具结果、候选人集合、证据引用。 |
| `RouterOutput` | graph state | 判断 scenario、context policy 和 open_recall 空结果策略。 |
| `session_context` | graph state | 检查上下文候选池是否被逃逸。 |
| `ResumeQAConfig` | graph state / `load_config()` | 读取 tool policy、evidence policy、validation rules。 |

## 输出

| 输出 | 去向 | 用途 |
|---|---|---|
| `ValidationResult.ok` | graph route | `true` 进入 aggregator，`false` 进入后续 repair / clarify / fail 路由。 |
| `errors[]` | graph route / trace | 阻塞性执行错误。 |
| `warnings[]` | aggregator / trace | 可继续回答但需要说明的风险。 |
| `error_details[]` | graph route | 用结构化 issue 决定 repair / clarify / fail。 |
| `next_node` | graph route | 成功默认 `aggregator`，失败默认 `execution_repair`。 |

## 它做什么

- 把 failed `ToolResult` 转成 execution validation error。
- 根据 intent 检查必需工具结果。
- 检查证据覆盖是否满足 YAML 策略。
- 检查 count 是否等于候选人来源数量。
- 检查双人比较是否确实返回两个人。
- 检查 open_recall 空结果是否需要 query fallback。
- 检查 ranking / profile / evidence 是否来自同一个候选人集合。

## 它不做什么

- 不调用工具。
- 不修复 `QueryPlan`。
- 不重跑 executor。
- 不扩大候选人范围。
- 不生成最终答案。
- 不决定最终 route；route 由 graph 和 `validation.yaml.issue_actions` 处理。

## 五类检查

### 1. Tool Failure

如果 executor 返回 failed `ToolResult`，并且不是允许的业务限制结果，就变成阻塞错误：

```text
tool_name failed: error
```

允许的业务限制来自 `tool_policy.yaml.business_limits`。例如候选人简介展示数量超过上限时，可以作为业务限制结果保留，而不是系统异常。

### 2. Required Results

每个 intent 需要哪些工具结果，由 `tool_policy.yaml.intent_result_requirements` 决定。

例子：

```yaml
candidate_count:
  all: [count_candidates]
candidate_ranking:
  all: [score_candidates_for_jd, rank_candidates]
candidate_profile_intro:
  any: [get_candidate_profile_intro, get_candidate_profiles_intro]
```

含义：

```text
candidate_count 必须有 count_candidates 结果
candidate_ranking 必须有 scoring 和 ranking 结果
candidate_profile_intro 至少要有单人或多人 profile 工具之一
```

### 3. Evidence Coverage

证据要求来自 `evidence_policy.yaml.intents`。

例子：

```yaml
candidate_ranking:
  requires_evidence: true
  min_evidence_per_candidate: 1
```

含义：

```text
排名结果里的候选人，每个人至少要有 1 条 EvidenceRef。
```

如果 evidence 工具正常运行但没有匹配证据，可能只是 warning；如果需要证据但完全没有 EvidenceRef，则是 error。

### 4. Result Consistency

检查工具结果之间是否自洽：

```text
count_candidates 的数量 == 前一个候选人列表的长度
build_comparison_pack 返回的人数 == validation.yaml.compare_pair.exact_candidate_count
open_recall 的 filter_candidates 空结果可进入 execution_repair query_fallback
```

### 5. Candidate Lineage

lineage 检查防止后续结果“跑出候选人池”。

例子：

```text
filter_candidates -> candidate_pool = [A, B, C]
rank_candidates -> ranked_candidates = [A, B, D]
```

这里 `D` 不在 canonical candidate pool 里，会报：

```text
semantic: ranked_candidates escaped canonical candidate_pool
```

同样，profile 和 evidence 也不能跑到 resolved candidates / canonical candidates 之外。

## 示例

问题：

```text
金融候选人有几个，谁最强，依据是什么？
```

executor 返回：

```text
filter_candidates ok -> candidate_pool: [A, B, C]
count_candidates ok -> 3
score_candidates_for_jd ok -> scores for [A, B, C]
rank_candidates ok -> [B, A, C]
search_candidate_evidence ok -> EvidenceRef for [B, A, C]
```

execution_validator 检查：

```text
1. 没有 failed ToolResult
2. candidate_count 有 count_candidates
3. candidate_ranking 有 score_candidates_for_jd + rank_candidates
4. count=3 等于 candidate_pool 长度 3
5. ranking 结果 [B, A, C] 没有跑出 [A, B, C]
6. evidence refs 覆盖了需要证据的候选人
```

如果全部通过：

```text
ValidationResult(ok=True, next_node="aggregator")
```

如果 `rank_candidates` 返回 `[B, A, D]`：

```text
ValidationResult(ok=False, errors=["semantic: ranked_candidates escaped canonical candidate_pool: ['D']"])
```

后续由 graph route 根据结构化 issue 决定进入 `execution_repair`、`clarification` 或 `fail`。

## 文档阅读顺序

```text
1. README.md
2. EXECUTION_VALIDATOR_FLOW.md
3. YAML_USAGE.md
4. execution.py
5. execution_requirements.py
6. execution_results.py
7. execution_lineage.py
```

## 验收命令

```bash
rg "Execution Validator|EXECUTION_VALIDATOR_FLOW|YAML_USAGE|validate_execution|validate_candidate_lineage|validate_required_tool_results" resume_query_ai_qa/nodes/execution_validator
./.venv/bin/python -m compileall -q resume_query_ai_qa/nodes/execution_validator
./.venv/bin/python resume_query_ai_qa/benchmarks/run_policy_contract_benchmark.py
./.venv/bin/python resume_query_ai_qa/benchmarks/run_plan_contract_benchmark.py
./.venv/bin/python resume_query_ai_qa/benchmarks/run_runtime_contract_benchmark.py
```
