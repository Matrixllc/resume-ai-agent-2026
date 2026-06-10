# Deployment Checklist

部署前按这份清单走，确保 Query-AI 架构、数据、API、前端和 benchmark 都处于可上线状态。

## 1. 环境

- Python 虚拟环境存在：`.venv/`
- Node 使用项目脚本固定到 Node 20：`resume_query_frontend_v3/scripts/use-node.sh`
- LLM 配置已确认：`resume_query_ai_qa/configs/llm.yaml`
- `.env` 中 compiler 推荐为 hybrid：

```text
RESUME_QA_WORKFLOW_TEMPLATE_COMPILER_ENABLED=true
RESUME_QA_GENERIC_TOOL_COMPILER_ENABLED=true
RESUME_QA_COMPILER_MODE=hybrid_template_binding
```

## 2. 数据

- SQLite 存在：`resume_query_v3/data/structured/structured_store.db`
- Chroma 存在：`resume_query_v3/data/vector/chroma_store`
- 如需覆盖路径，设置：

```text
RESUME_TOOLS_SQLITE=
RESUME_TOOLS_CHROMA_DIR=
RESUME_TOOLS_CHROMA_COLLECTION=
```

入库和文件预览仍是 demo/数据底座边界；生产展示重点是 Query-AI 主链。

## 3. 后端启动

```bash
./.venv/bin/uvicorn resume_query_api.main:app --host 127.0.0.1 --port 8000
```

检查：

```text
GET http://127.0.0.1:8000/health
GET http://127.0.0.1:8000/candidates
POST http://127.0.0.1:8000/qa/ask
POST http://127.0.0.1:8000/qa/ask?debug=true
```

`/qa/ask` 非 Debug 响应也必须包含最小 `trace.diagnosis`；`debug=true` 才返回
`decision_steps`、`route_events`、compiled plan、tools 和日志定位。

## 4. 前端启动与构建

```bash
cd resume_query_frontend_v3
./scripts/use-node.sh
npm install
npm run dev:local
```

访问：

```text
http://127.0.0.1:3000
```

生产构建：

```bash
cd resume_query_frontend_v3
./scripts/use-node.sh
npm run build
```

`npm run lint` 当前会进入交互式 ESLint 初始化；上线阻塞先以 `npm run build` 为准。
要把 lint 纳入阻塞项，需要先补非交互 ESLint 配置。

## 5. 必跑 Benchmark

```bash
.venv/bin/python -m compileall -q resume_query_ai_qa resume_query_api resume_query_tools
.venv/bin/python resume_query_ai_qa/benchmarks/run_plan_contract_benchmark.py
.venv/bin/python resume_query_ai_qa/benchmarks/run_plan_contract_benchmark.py
.venv/bin/python resume_query_ai_qa/benchmarks/run_plan_contract_benchmark.py
.venv/bin/python resume_query_ai_qa/benchmarks/run_policy_contract_benchmark.py
.venv/bin/python resume_query_ai_qa/benchmarks/run_runtime_contract_benchmark.py
.venv/bin/python resume_query_ai_qa/benchmarks/run_plan_contract_benchmark.py
.venv/bin/python resume_query_ai_qa/benchmarks/run_runtime_contract_benchmark.py
.venv/bin/python resume_query_ai_qa/benchmarks/run_llm_acceptance_benchmark.py --mode hybrid --retries 1
```

建议压测：

```bash
.venv/bin/python resume_query_ai_qa/benchmarks/run_llm_acceptance_benchmark.py --mode hybrid --retries 1 --repeat 3
.venv/bin/python resume_query_ai_qa/benchmarks/run_domain_matrix_benchmark.py
```

## 6. 人工 Trace 抽查

至少看这些问题：

| 问题 | 重点看 |
| --- | --- |
| `介绍一下孟连星` | `ExecutionDecision.compiler=workflow_template`，不出现 planner。 |
| `可能的金融领域候选人` | `scenario=open_recall`，允许 hybrid。 |
| `金融领域候选人有哪些？` | `scenario=hard_filter`，必须 structured filter。 |
| `孙可欣 有能源相关的经历么` | evidence 为空时 `ok + empty_evidence warning`。 |
| `他有哪些金融经历？` | `needs_clarification + required_context_missing`，前端能看懂原因。 |
| `今天天气怎么样？` | out_of_scope，不执行简历工具。 |

每个样例都看：

- 状态卡是否展示 `diagnosis.headline`。
- Debug 摘要是否有 `route_events`。
- 节点时间线是否有 `status + summary`。
- 失败时是否能看到 `failed_node`、`failed_reason` 和 validator errors。
- `trace_lookup` 是否能定位 detail JSON。

## 7. 部署包边界

纳入部署：

- `resume_query_ai_qa`
- `resume_query_api`
- `resume_query_tools`
- `resume_query_frontend_v3` 源码和构建产物
- `resume_query_v3` 数据底座和 ingestion 代码

不纳入运行主链：

- `rewrite_v1`
- `resume_query_v2`
- 历史 logs
- `__pycache__`
- `.DS_Store`
- `node_modules`

## 8. 失败处理

- intent 错：看 router 和 `router_rules.yaml`。
- template/generic 错：看 `execution_policy` 和 `compiler_templates.yaml`。
- 工具协议错：看 `plan_compiler`、`tool_policy.yaml`、`plan_validator`。
- 工具执行错：看 executor tool results、`tool_failures[]`、`execution_validator`。
- 证据为空：先确认是正常 0 结果还是工具异常；正常空证据应为 `empty_evidence`。
- 答案错：看 aggregator details、answer validator errors、answer rewrite route。
- 前端看不懂：先看 API `diagnosis` 是否完整，再看 Debug 面板字段映射。
