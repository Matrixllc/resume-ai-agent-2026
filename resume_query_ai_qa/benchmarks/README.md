# QA Graph Benchmarks

`benchmarks/` 是 Query-AI 的合同回归层。它不是简单跑几个 demo 问题，而是用同一份生产配置验证：

```text
policy 是否选对
-> plan 是否编译正确
-> runtime 是否执行并回答正确
```

所有业务问题统一维护在 `benchmark_cases.yaml`。case 只声明业务语义、上下文和安全边界；
工具链、artifact、workflow、validation action 与 aggregator mode 都从生产配置解析。

## 它证明什么

| Benchmark | 证明点 | 典型问题 |
| --- | --- | --- |
| `policy` | router intent/scenario、execution_policy、允许/禁止工具是否符合 YAML 合同。 | 问法变化后有没有走错 intent 或 workflow。 |
| `plan` | compiler、canonical source、artifact binding、validator 是否生成合法 `QueryPlan`。 | `$binding`、`$ref`、候选池来源、工具参数有没有错。 |
| `runtime` | executor、execution_validator、aggregator、answer_validator、trace/log 合同是否闭环。 | 工具结果、空证据、fallback、最终答案是否能安全返回。 |
| `domain_matrix` | 同一模板在多个业务领域参数化后是否稳定。 | Operations / Finance / Energy 等领域是否有偏置或断链。 |
| `llm_acceptance` | 真实 `use_llm=True` 完整 graph 是否在外部 LLM 可用时通过。 | LLM fill、rewrite、grounding、fallback 是否能协同。 |

## 日常必跑

改 router、policy、scenario、intent 后：

```bash
.venv/bin/python resume_query_ai_qa/benchmarks/run_policy_contract_benchmark.py
```

改 planner、compiler、tool policy、template、validator 后：

```bash
.venv/bin/python resume_query_ai_qa/benchmarks/run_plan_contract_benchmark.py
```

改 executor、tools、execution_validator、aggregator、answer_validator、repair/fallback 后：

```bash
.venv/bin/python resume_query_ai_qa/benchmarks/run_runtime_contract_benchmark.py
```

跨层修改后，至少跑：

```bash
.venv/bin/python resume_query_ai_qa/benchmarks/run_policy_contract_benchmark.py
.venv/bin/python resume_query_ai_qa/benchmarks/run_plan_contract_benchmark.py
.venv/bin/python resume_query_ai_qa/benchmarks/run_runtime_contract_benchmark.py
```

## 上线 / 演示前跑

```bash
.venv/bin/python resume_query_ai_qa/benchmarks/run_policy_contract_benchmark.py
.venv/bin/python resume_query_ai_qa/benchmarks/run_plan_contract_benchmark.py
.venv/bin/python resume_query_ai_qa/benchmarks/run_runtime_contract_benchmark.py
.venv/bin/python resume_query_ai_qa/benchmarks/run_domain_matrix_benchmark.py
```

如果要验证真实 LLM 链路，再跑：

```bash
.venv/bin/python resume_query_ai_qa/benchmarks/run_llm_acceptance_benchmark.py --mode hybrid --repeat 3
```

`llm_acceptance` 会做网络/LLM 预检；如果外部 LLM 不可用，会提前退出，不应该把它和离线合同回归混为一谈。

## 演讲时怎么讲

可以这样讲 benchmark：

```text
我没有只靠人工看答案。
系统分三层回归：
policy 确认问题被理解到正确 intent/scenario；
plan 确认工具链、参数和 artifact binding 合法；
runtime 确认工具结果、fallback、answer validator 和 trace 都能闭环。
```

这和普通单测的区别是：benchmark 直接跑生产配置和真实 graph，验证的是“整条链是否还符合合同”。

## Case 来源

`benchmark_cases.yaml` 是业务 case 的统一入口。它不写死工具链，而是声明用户问题、期望语义、
安全边界和上下文场景。

这样做的好处：

- 改 YAML 合同时，benchmark 能发现上下游是否同步。
- 改 compiler/validator 时，case 不需要复制工具细节。
- 同一问题可以在 policy / plan / runtime 三层复用。

## LLM 验收边界

LLM 验收从正式 graph state 和 trace 字段读取结果：

- `state.plan`
- `state.tool_results`
- `trace.decision_steps`
- `trace.route_events`
- aggregator meta

`llm_fill`、`llm_fill_rejected`、规则 grounded renderer 与 LLM 错误后的规则 fallback 都由
`aggregator_tasks.yaml` 声明是否合法；`llm_fill_rejected` 单独计数，便于判断是 LLM 表达失败，
还是主链合同失败。

## 不做什么

- 不替代单元测试。
- 不替代线上监控。
- 不保证外部 LLM 服务稳定。
- 不把 benchmark case 当业务配置真源。
- 不在 case 中绕过生产 YAML 决策。

## 相关文档

- [../README.md](../README.md)
- [../nodes/README.md](../nodes/README.md)
- [../nodes/NODES_FLOW.md](../nodes/NODES_FLOW.md)
- [../configs/README.md](../configs/README.md)
- [DEPLOYMENT_ACCEPTANCE.md](DEPLOYMENT_ACCEPTANCE.md)
