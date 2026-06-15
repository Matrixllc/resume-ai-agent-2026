# Plan Repair Node

一句话：`plan_repair` 只修复 `plan_validator` 判定为可修复的非法 `QueryPlan`，修完必须回到 `plan_validator` 复检。

## 架构位置

```text
plan_compiler
-> plan_validator
   -> ok: executor
   -> repair: plan_repair
   -> clarify: clarification
   -> fail: fail

plan_repair
-> plan_validator
```

固定边界：

```text
plan_validator = 发现非法 QueryPlan
plan_repair = 只修可修复的 plan
plan_repair 修完必须回 validator
executor = 只执行验证通过的 plan
```

## 节点目标

`plan_repair` 的默认策略不是在坏 plan 上随意 patch，而是：

```text
基于 RouterOutput 重新构建一个确定性 QueryPlan
```

它做：

- 根据 validator 错误和 `validation.yaml` 决定 repair / clarify / fail。
- 对可修复错误执行 rule rebuild。
- 默认不启用 LLM repair。
- 修复后刷新 structured refs 和 artifact bindings。
- 把 repaired plan 交回 `plan_validator`。

它不做：

- 不调用 tools。
- 不直接进入 executor。
- 不忽略 validator 错误。
- 不用 repair 掩盖缺上下文。
- 不放宽 tool policy 或 candidate scope。

## 输入 / 输出

输入：

| 字段 | 来源 | 用途 |
|---|---|---|
| `question` | 用户问题 | 重建工具 query / TopK 约束。 |
| `router_output` | router + condition_normalizer | 修复时的权威 intent、conditions、context。 |
| `previous_plan` | plan_compiler / validator | 上一个非法 QueryPlan；clarify/fail 时保留。 |
| `validation_errors` | plan_validator | 错误文本。 |
| `validation_issues` | behavior_contract | 结构化错误分类。 |
| `session_context` | graph state | 上下文候选人池、ranking top、comparison pair。 |
| `config` | YAML 加载结果 | repair 策略、tool policy、validation rules。 |
| `use_llm` | graph/runtime | 是否允许 LLM repair。 |

输出：

| 返回项 | 说明 |
|---|---|
| `QueryPlan` | repaired plan，或 terminal action 时保留 previous plan。 |
| `decision` | `action/category/reason`。 |
| `engine` | `rule` / `llm` / `rule_fallback`。 |
| `fallback_reason` | LLM 失败或规则回退原因。 |

## 四条路径

### rule repair

默认路径：

```text
validation error
-> classify_plan_repair_action
-> action=rule_repair
-> build_rule_plan
-> refresh_artifact_bindings
-> plan_validator
```

### LLM repair

默认关闭：

```yaml
plan_repair:
  llm_enabled: false
```

只有 semantic 错误、显式启用 LLM repair、LLM 可用、且不属于 deterministic intent 时才会尝试。

### clarify

例如缺少上下文：

```text
missing required context
-> action=clarify
-> graph route: clarification
```

### fail

例如不可修复的 argument binding 或工具执行合同错误：

```text
argument_binding
-> action=fail
-> graph route: fail
```

## 示例

问题：

```text
金融候选人有几个？
```

坏 plan：

```text
list_all_candidates -> count_candidates
```

validator 报错：

```text
semantic: filtered candidate scope cannot be produced by all-scope source list_all_candidates
```

repair 分类：

```text
semantic_contract
-> rule_repair
```

rule rebuild 使用 `RouterOutput`：

```text
intent = candidate_count
normalized_conditions = domain: 金融
```

重建后：

```text
filter_candidates(domains_any=["金融"]) -> candidate_pool
count_candidates(candidate_pool)
```

然后：

```text
refresh_artifact_bindings
-> plan_validator
```

只有再次通过 validator，才会进入 executor。

## 文档阅读顺序

```text
1. README.md
2. PLAN_REPAIR_FLOW.md
3. YAML_USAGE.md
4. plan.py
5. llm.py
```

## 验收命令

```bash
./.venv/bin/python -m compileall -q resume_query_ai_qa/nodes/plan_repair
./.venv/bin/python resume_query_ai_qa/benchmarks/run_policy_contract_benchmark.py
./.venv/bin/python resume_query_ai_qa/benchmarks/run_plan_contract_benchmark.py
./.venv/bin/python resume_query_ai_qa/benchmarks/run_runtime_contract_benchmark.py
```
