# Planner Node

一句话：`planner` 在 generic 路径里，把 `RouterOutput + ExecutionDecision` 收敛成 `SemanticPlan`。

## 架构位置

```text
user question
-> router
-> condition_normalizer
-> execution_policy
   -> template: plan_compiler
   -> generic: planner
-> plan_compiler
-> plan_validator
-> executor
-> aggregator / answer_rewrite
```

`planner` 只在 `execution_policy` 判定为 `generic_tool_binding` 时运行。稳定 template 路径会跳过 planner，直接进入 `plan_compiler`。

## 节点目标

planner 只回答：

```text
语义上要做几步？
每一步是什么 intent / scenario？
每一步需要哪些 semantic needs？
每一步可以给 compiler 哪些 tool hints？
```

它产出 `SemanticPlan`，不是可执行计划。

```text
SemanticPlan = 语义中间计划
QueryPlan = 可执行工具计划
```

## 它做什么

- 根据 `ExecutionDecision.planner` 选择 rule planner 或 LLM planner。
- rule planner 用 router 输出和 YAML 生成稳定 `SemanticPlan`。
- LLM planner 只生成 `SemanticPlan draft`，随后必须经过 authority normalize。
- LLM 不可用或失败时，回退到 rule planner。
- 给 `plan_compiler` 提供 `tool_hints`，但不生成最终工具调用。

## 它不做什么

- 不重新判断 intent。
- 不重新生成 scenario。
- 不生成 `ToolCallSpec`。
- 不拼 `$ref`、`depends_on`、`output_key`。
- 不调用 tools。
- 不查数据库或向量库。
- 不回答用户问题。

## 输入 / 输出

输入：

| 字段 | 来源 | 用途 |
|---|---|---|
| `question` | 用户问题 | LLM planner prompt 使用。 |
| `RouterOutput.intent` | router/finalizer | SemanticPlan 主 intent。 |
| `RouterOutput.sub_intent_candidates` | router/finalizer | compound 时生成多个 step。 |
| `RouterOutput.normalized_conditions` | condition_normalizer | 每个 step 继承标准化条件。 |
| `RouterOutput.context_policy` | router/guard | 下游 compiler/validator 使用上下文策略。 |
| `RouterOutput.requires_jd` | router/finalizer | step 是否需要 JD 标准。 |
| `RouterOutput.requires_evidence` | router/finalizer | step 是否需要证据。 |
| `RouterOutput.sub_intent_evidence` | router/finalizer | 每个子 intent 的 evidence 文本。 |
| `ExecutionDecision.planner` | execution_policy | 选择 rule 或 LLM planner。 |
| `ExecutionDecision.scenarios` | execution_policy | LLM prompt 上下文；scenario 权威仍来自 RouterOutput。 |
| `config` | YAML 加载结果 | 读取 semantic needs、tool hints 和 planner 策略。 |

输出：

| 字段 | 说明 | 给谁用 |
|---|---|---|
| `SemanticPlan.intent` | 主 intent | plan_compiler。 |
| `SemanticPlan.is_compound` | 是否复合问题 | plan_compiler。 |
| `SemanticPlan.steps[]` | 每个子任务的语义步骤 | plan_compiler。 |
| `SemanticPlan.context_policy` | 上下文策略 | compiler/validator。 |
| `SemanticPlan.normalized_conditions` | 标准化条件 | compiler/validator。 |
| `SemanticPlan.compile_strategy` | 编译策略标记 | compiler trace / fallback。 |
| `SemanticPlan.notes` | 生成来源说明 | trace。 |
| `meta.engine` | `rule` / `llm` / `rule_fallback` | trace。 |

## 主流程

```text
resolve_semantic_plan
-> decision.planner == rule ?
   -> semantic_plan_from_router
-> decision.planner == llm ?
   -> semantic_plan_llm
   -> normalize_semantic_plan
   -> fallback: semantic_plan_from_router
```

rule 路径：

```text
semantic_plan_from_router
-> semantic_step_from_config
-> SemanticPlan
```

LLM 路径：

```text
semantic_plan_llm
-> _planner_prompt_context
-> invoke_structured(SemanticPlan)
-> normalize_semantic_plan
-> SemanticPlan
```

## 准确性保障

- `RouterOutput` 是 intent、conditions、context 的权威来源。
- `scenario` 从 `RouterOutput.scenario_decisions` 读取，不由 planner 重新判断。
- rule planner 完全由 YAML 和 router 输出生成，LLM 失败也有确定性回退。
- LLM draft 必须经过 `normalize_semantic_plan`，不能越权改 intent、conditions、context。
- tool hints 只是建议，最终工具和参数由 `plan_compiler` 绑定。

## 文档阅读顺序

```text
1. README.md
2. PLANNER_FLOW.md
3. YAML_USAGE.md
4. planner.py
5. llm.py
6. rules.py
7. ../../core/rules/semantic_plan.py
```

## 验收命令

```bash
./.venv/bin/python -m compileall -q resume_query_ai_qa/nodes/planner resume_query_ai_qa/core/rules/semantic_plan.py
./.venv/bin/python resume_query_ai_qa/benchmarks/run_policy_contract_benchmark.py
./.venv/bin/python resume_query_ai_qa/benchmarks/run_plan_contract_benchmark.py
```
