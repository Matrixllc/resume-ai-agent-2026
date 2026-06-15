# Plan Validator Node

一句话：`plan_validator` 是执行前的只读合同闸门，判断 `QueryPlan` 能不能安全交给 executor。

## 架构位置

```text
router
-> condition_normalizer
-> execution_policy
-> planner / plan_compiler
-> plan_validator
   -> ok: executor
   -> error: plan_repair / clarification / fail
```

固定边界：

```text
plan_compiler = 生成 QueryPlan
plan_validator = 执行前合同检查
plan_repair = 尝试修复非法计划
executor = 真正执行工具
```

## 节点目标

`plan_validator` 只读检查 `QueryPlan`。

它做：

- 检查工具是否允许、是否存在、参数是否符合签名。
- 检查 `depends_on` 和 `$ref` 是否引用了已经产出的 `output_key`。
- 检查 count/ranking/compare 这类 intent 的专属边界。
- 检查 candidate source、artifact binding、workflow artifact contract。
- 检查计划是否满足 `RouterOutput` 的语义、条件、上下文和证据要求。
- 输出 `ValidationResult`，交给 graph 路由。

它不做：

- 不生成 `QueryPlan`。
- 不修改或修复 plan。
- 不调用 tools。
- 不判断工具执行结果。
- 不生成最终答案。

## 输入 / 输出

输入：

| 字段 | 来源 | 用途 |
|---|---|---|
| `QueryPlan` | plan_compiler / repair | 被校验对象。 |
| `RouterOutput` | router + condition_normalizer | intent、conditions、context、requires flags。 |
| `session_context` | graph state | 检查上一轮候选人池、排名、对比对象是否存在。 |
| `config` | YAML 加载结果 | tool policy、scenario、validation、workflow artifact contracts。 |
| tool registry | tools registry | 检查工具名和函数签名。 |

输出：

| 字段 | 说明 | 给谁用 |
|---|---|---|
| `ValidationResult.ok` | 是否通过 | graph route。 |
| `errors` | 阻塞错误 | repair/trace。 |
| `warnings` | 非阻塞提示 | trace。 |
| `error_details` | 结构化问题分类 | behavior contract / graph route。 |
| `repair_hint` | 修复提示 | plan_repair。 |
| `next_node` | 建议下一跳 | graph route。 |

## 五类检查

### 1. Structure

文件：

```text
plan_structure.py
```

检查：

```text
tool exists
tool arguments match signature
allowed_tools / forbidden_tools
depends_on
$ref
output_key
scenario contract
out_of_scope no tools
```

### 2. Boundaries

文件：

```text
plan_boundaries.py
```

检查：

```text
candidate_compare_pair 必须刚好 2 个候选人
candidate_ranking 必须 criteria -> score -> rank
candidate_count 必须 candidate source -> count
```

### 3. Artifacts

文件：

```text
plan_artifacts.py
```

检查：

```text
candidate_collection 是否有唯一 canonical source
count/score/evidence 是否消费正确来源
hard domain 不能被 list_all_candidates 或 query-only hybrid 代替
workflow artifact_contracts 是否满足
```

### 4. Semantics

文件：

```text
plan_semantics.py
```

检查：

```text
compound 是否包含所有 sub intents
normalized_conditions 是否进入计划
hard_filter 是否使用结构化 filter
context_policy 是否有可用上下文
context candidate_ids 是否真的限制到工具参数
requires_evidence 是否有 evidence-capable tool
```

### 5. Result Routing

文件：

```text
plan.py
```

输出：

```text
ok=True
-> next_node=executor

ok=False
-> errors
-> error_details
-> next_node=plan_repair
```

graph 后续会根据 `ValidationResult` 和 issue action 继续路由到 repair、clarification 或 fail。

## 示例

问题：

```text
金融候选人有几个，谁最强，依据是什么？
```

compiler 产出：

```text
candidate_count:
  filter_candidates(domains_any=["金融"]) -> candidate_pool
  count_candidates(candidate_pool)

candidate_ranking:
  load_default_jd_criteria() -> criteria
  score_candidates_for_jd(candidate_pool, criteria) -> scores
  rank_candidates(scores) -> ranked_candidates

evidence_question:
  search_candidate_evidence(ranked_candidates) -> candidate_evidence
```

validator 检查：

```text
structure:
  工具存在，参数合法，depends_on/$ref 指向已有 output_key

boundaries:
  count 有 candidate source + count_candidates
  ranking 有 criteria + score + rank

artifacts:
  candidate_pool 是 canonical candidate_collection
  score 消费 candidate_pool
  evidence 消费 ranked_candidates

semantics:
  compound 包含 count/ranking/evidence 三个子 intent
  domain=金融 进入 filter_candidates.domains_any
  requires_evidence=true 且有 search_candidate_evidence
```

全部通过：

```text
ValidationResult(ok=True, next_node="executor")
```

## 文档阅读顺序

```text
1. README.md
2. PLAN_VALIDATOR_FLOW.md
3. YAML_USAGE.md
4. plan.py
5. plan_structure.py
6. plan_boundaries.py
7. plan_artifacts.py
8. plan_semantics.py
```

## 验收命令

```bash
./.venv/bin/python -m compileall -q resume_query_ai_qa/nodes/plan_validator
./.venv/bin/python resume_query_ai_qa/benchmarks/run_policy_contract_benchmark.py
./.venv/bin/python resume_query_ai_qa/benchmarks/run_plan_contract_benchmark.py
./.venv/bin/python resume_query_ai_qa/benchmarks/run_runtime_contract_benchmark.py
```
