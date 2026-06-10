# Deployment Acceptance

部署前依次运行：

```bash
.venv/bin/python resume_query_ai_qa/benchmarks/run_policy_contract_benchmark.py
.venv/bin/python resume_query_ai_qa/benchmarks/run_plan_contract_benchmark.py
.venv/bin/python resume_query_ai_qa/benchmarks/run_runtime_contract_benchmark.py
.venv/bin/python resume_query_ai_qa/benchmarks/run_domain_matrix_benchmark.py
.venv/bin/python resume_query_ai_qa/benchmarks/run_llm_acceptance_benchmark.py --mode hybrid --repeat 3
```

验收重点：

- follow-up 必须收敛到具体业务 intent。
- 缺少所需上下文必须进入 `needs_clarification`。
- 单候选人岗位适配不得扩大为全候选人评分或排序。
- benchmark 从正式 state/trace 合同读取数据，不依赖 deep debug 字段。
- router/planner 在 LLM 验收中不得静默 rule fallback。
