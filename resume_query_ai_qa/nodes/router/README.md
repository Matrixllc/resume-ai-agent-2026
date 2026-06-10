# Router Node

Router 把用户问题收敛成 `RouterOutput`。

它是 Query-AI 的语义入口：把自然语言问题变成后续节点能执行的结构化意图。
它不查 SQLite/Chroma，不调用 tools，不生成工具计划，也不回答用户问题。

## 架构位置

```text
user question
-> router
-> condition_normalizer
-> execution_policy
-> planner / plan_compiler
-> executor
-> aggregator
-> validator / rewrite
-> final answer
```

router 的输出不是给用户看的，而是给后续节点消费的协议。

## 它实现了什么

router 负责判断：

```text
intent
compound / sub_intents
raw conditions
context reference
scenario decisions
requires_jd / requires_evidence
risk_flags
```

也就是：

```text
自然语言问题 -> 结构化执行意图
```

## RouterOutput 给谁用

| 字段 | 后续消费者 | 用途 |
|---|---|---|
| `intent` | execution_policy / planner | 判断主任务类型 |
| `sub_intent_candidates` | planner / compiler | 拆 compound 子任务 |
| `scenario_decisions` | execution_policy / compiler | 决定执行场景和 planner 类型 |
| `conditions` | condition_normalizer | 归一化 domain/skill/candidate_name 等条件 |
| `context_policy` | execution_policy / compiler | 解析“第一名/这些人/刚才那个人”等引用 |
| `requires_jd` | planner / compiler | 判断是否需要 JD criteria |
| `requires_evidence` | planner / validator / aggregator | 判断是否必须查证据 |
| `allowed_tool_names` | compiler / validator | 单 intent 工具白名单 |
| `risk_flags` | trace / validator / debug | 记录 fallback、guard、修补原因 |

## 主流程

```text
preprocess_router_question
-> build_router_draft
-> apply_router_guards
-> complete_router_conditions
-> finalize_router_output
-> RouterOutput
```

每一步的角色：

| 阶段 | 作用 |
|---|---|
| preprocess | 轻量清理问题，统一标点，去掉开头 filler terms |
| draft | 通过 LLM 或 rule fallback 生成 RouterOutput 草稿 |
| guards | 用硬规则纠偏敏感问题、排序、对比、证据、上下文、复合任务 |
| condition completion | 补漏掉的 raw `QueryCondition` |
| finalizer | 三段式权威收口：shape / contract / derived flags |

rule-only 路径跳过 LLM，但仍执行 guards、condition completion 和 finalizer。

## 怎么保证准确

router 不依赖单一判断，而是五层稳定机制：

| 层 | 作用 |
|---|---|
| LLM schema 校验 | LLM 输出必须符合 `RouterOutput`，intent/scenario 不合法就 fallback |
| rule fallback | LLM 不可用时，规则路径仍可独立生成 draft |
| guard 硬规则纠偏 | 对敏感问题、两人对比、多人排序、证据追问、上下文引用等强规则覆盖 |
| condition completion | 再跑条件抽取，补齐 domain/skill/major/scope/candidate_name |
| finalizer 权威收口 | 统一修正字段自洽、YAML 合同和派生 flags |

finalizer 的三段式：

```text
Shape 收口：intent / is_compound / sub_intents / evidence / conditions 自洽
Contract 收口：scenario/tool 符合 scenarios.yaml 和 tool_policy.yaml
Derived Flags 收口：requires_jd / requires_evidence / risk_flags 最终可信
```

## 文档阅读顺序

```text
1. README.md
2. ROUTER_FLOW.md
3. YAML_USAGE.md
4. node.py
5. llm.py
6. rules.py
7. signals.py
8. guard.py
9. conditions.py
10. finalizer.py
11. rule_types.py
```

三份文档分工：

| 文档 | 作用 |
|---|---|
| `README.md` | 总览入口：router 在架构中做什么、怎么保证准确 |
| `ROUTER_FLOW.md` | 代码阅读线：按 pipeline 和函数顺序读代码 |
| `YAML_USAGE.md` | YAML 字段地图：区分 router 直接/间接使用的 YAML |

## 边界

router 能做：

```text
判断 intent / scenario / compound
生成 raw conditions
解析 context reference
标记 risk flags
安全拦截 out_of_scope
```

router 不能做：

```text
不查 SQLite/Chroma
不生成 ToolCallSpec
不拼工具参数
不调用 tools
不生成最终答案
```

## 验收

```bash
./.venv/bin/python -m compileall -q resume_query_ai_qa/nodes/router
./.venv/bin/python resume_query_ai_qa/benchmarks/run_policy_contract_benchmark.py
./.venv/bin/python resume_query_ai_qa/benchmarks/run_plan_contract_benchmark.py
```
