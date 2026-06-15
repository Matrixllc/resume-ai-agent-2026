# Execution Policy Node

一句话：`execution_policy` 把已经标准化的 `RouterOutput` 收敛成 `ExecutionDecision`，决定本轮走稳定 workflow template，还是走通用 planner。

## 架构位置

```text
user question
-> router
-> condition_normalizer
-> execution_policy
   -> template: plan_compiler
   -> generic: planner -> plan_compiler
-> plan_validator
-> executor
-> aggregator / answer_rewrite
```

`execution_policy` 位于 `condition_normalizer` 之后。它已经能读到 router 的 intent/scenario，也能读到标准化后的 conditions，所以可以判断当前问题是否命中一个稳定 workflow。

## 节点目标

它做三件事：

- 读取 `RouterOutput.intent`、`sub_intent_candidates`、`scenario_decisions` 和 `normalized_conditions`。
- 用 `compiler_templates.yaml.workflows.*.match` 判断是否命中稳定 workflow。
- 输出 `ExecutionDecision`，给 graph 决定下一跳。

它不做这些事：

- 不重新判断 intent。
- 不重新生成 scenario。
- 不生成 `SemanticPlan` 或 `QueryPlan`。
- 不拼工具参数。
- 不调用 tools。
- 不回答用户问题。

## 输入 / 输出

输入：

| 字段 | 来源 | 用途 |
|---|---|---|
| `question` | 用户问题 | 只用于透传、trace、少量 rule fallback 场景函数。 |
| `RouterOutput.intent` | router/finalizer | workflow 匹配的主 intent。 |
| `RouterOutput.sub_intent_candidates` | router/finalizer | compound workflow 检查必需子 intent。 |
| `RouterOutput.scenario_decisions` | router/finalizer | workflow 匹配 scenario；generic 路径选择 planner。 |
| `RouterOutput.normalized_conditions` | condition_normalizer | 判断 `requires_scope` 是否成立。 |
| `RouterOutput.context_policy` | router/guard | 上下文候选人池也可作为 scope。 |
| `ResumeQAConfig.compiler_templates` | `compiler_templates.yaml` | workflow 匹配表。 |
| `ResumeQAConfig.compiler_flags()` | `.env` / 默认值 | 决定 template/generic/hybrid 模式。 |

输出：

| 字段 | 说明 | 给谁用 |
|---|---|---|
| `compiler` | `workflow_template` 或 `generic_tool_binding` | graph 条件路由。 |
| `planner` | generic 路径使用 `rule` 或 `llm` planner | planner 节点。 |
| `workflow_name` | 命中的 workflow 名称 | plan_compiler template 路径。 |
| `scenarios` | 每个 intent 对应的 scenario | planner/compiler/validator。 |
| `reason` | 为什么走这条路径 | trace 和排查。 |

## 主流程

```text
resolve_execution_policy
-> resolve_execution_decision
-> _router_intents
-> scenario_for_intent
-> compiler_flags
-> match_workflow
-> _workflow_matches
-> ExecutionDecision
-> route_after_execution_policy
```

graph 根据 `route_after_execution_policy` 返回值分流：

```text
compiler == workflow_template
-> plan_compiler

compiler == generic_tool_binding
-> planner
```

## Workflow 怎么匹配

简单理解：

```text
workflow.match 里写了什么，就检查什么；
写了的条件全部通过，这个 workflow 才算命中；
没有写的条件，不参与判断。
```

当前支持的匹配条件：

| match 字段 | 判断方式 |
|---|---|
| `intent` | 必须等于 `RouterOutput.intent`。 |
| `intents` | `RouterOutput.intent` 必须在列表里。 |
| `required_sub_intents` | 列表里的子 intent 必须都在 `sub_intent_candidates` 里。 |
| `scenarios` | 当前 scenarios 里至少一个命中列表。 |
| `requires_scope` | 必须有明确筛选范围，或上下文候选人池。 |

例如：

```text
金融候选人有几个，谁最强，依据是什么？
```

如果 router 产出：

```text
intent = compound
sub_intent_candidates = [candidate_count, candidate_ranking, evidence_question]
scenario = hard_filter / compare_rank / fact_check
normalized_conditions = domain: 金融
```

就能命中 `scoped_count_rank_evidence`：

```yaml
match:
  intent: compound
  required_sub_intents:
    - candidate_count
    - candidate_ranking
    - evidence_question
  requires_scope: true
```

因为 intent 对上、三个子 intent 都有，而且 `domain: 金融` 让 `requires_scope` 成立。

## 准确性保障

- Router/finalizer 先把 intent、scenario、requires flags 收口，本节点不重复理解自然语言。
- `condition_normalizer` 先生成 `normalized_conditions`，本节点只用它判断 scope。
- `compiler_templates.yaml` 用优先级排序，高优先级 workflow 先匹配。
- 没有 workflow 命中不是错误，会自动走 generic planner。
- compiler 模式由 `compiler_flags()` 统一校验，避免节点内部散落环境变量判断。

## 文档阅读顺序

```text
1. README.md
2. EXECUTION_FLOW.md
3. YAML_USAGE.md
4. execution_policy.py
5. ../../core/rules/execution_policy_rules.py
6. ../../configs/compiler_templates.yaml
```

## 验收命令

```bash
./.venv/bin/python -m compileall -q resume_query_ai_qa/nodes/execution_policy resume_query_ai_qa/core/rules/execution_policy_rules.py
./.venv/bin/python resume_query_ai_qa/benchmarks/run_policy_contract_benchmark.py
./.venv/bin/python resume_query_ai_qa/benchmarks/run_plan_contract_benchmark.py
```
