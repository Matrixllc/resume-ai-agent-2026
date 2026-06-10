# QA Graph Benchmarks

所有业务问题统一维护在 `benchmark_cases.yaml`。case 只声明业务语义、上下文和安全边界；工具链、artifact、workflow、validation action 与 aggregator mode 均从生产配置解析。

主命令：

```bash
.venv/bin/python resume_query_ai_qa/benchmarks/run_policy_contract_benchmark.py
.venv/bin/python resume_query_ai_qa/benchmarks/run_plan_contract_benchmark.py
.venv/bin/python resume_query_ai_qa/benchmarks/run_runtime_contract_benchmark.py
.venv/bin/python resume_query_ai_qa/benchmarks/run_domain_matrix_benchmark.py
.venv/bin/python resume_query_ai_qa/benchmarks/run_llm_acceptance_benchmark.py --mode hybrid --repeat 3
```

职责：

- `policy`：配置一致性、router intent/scenario、允许与禁止工具。
- `plan`：compiler、canonical source、artifact binding、validator。
- `runtime`：executor、aggregator、answer validator、trace/log 合同。
- `domain_matrix`：同一模板参数化验证 Operations、Finance、Energy。
- `llm_acceptance`：真实 `use_llm=True` 完整 graph；网络预检失败时立即退出。

LLM 验收从 `state.plan`、`state.tool_results` 和正式 trace 字段读取结果。`llm_fill`、`llm_fill_rejected`、规则 grounded renderer 与 LLM 错误后的规则 fallback 都由 `aggregator_tasks.yaml` 声明是否合法；`llm_fill_rejected` 单独计数。
