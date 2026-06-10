# Query-AI 修改指南

修改前先回答：问题出在理解、计划、工具事实、答案表达，还是校验边界？不要为了修一个答案
同时修改多层。

## 修改入口速查

| 目标 | 首选入口 | 必跑测试 |
| --- | --- | --- |
| 新增或调整问法 | `configs/router_rules.yaml`、`configs/intents.yaml`、router | router contract、hybrid full |
| 新增稳定工作流 | `configs/compiler_templates.yaml`、plan compiler | semantic compiler、boundary |
| 新增只读工具 | tools 实现、registry、`tool_policy.yaml` | executor、plan validator、boundary |
| 修改答案结构 | `aggregator_tasks.yaml`、`answer_layouts.yaml` | aggregator、answer validator |
| 修改校验规则 | 对应 validator、`validation.yaml` | 对应 validator contract、bad case |
| 修改领域/技能筛选结果 | tools 与入库标签 | structured filter、domain diversity |
| 修改日志/trace | state、observability、API diagnosis | structure、bad-case debug、log CLI |

## 新增或调整问法

1. 判断它属于现有 intent，还是确实需要新 intent。
2. 正常 LLM 路径优先调整 `intents.yaml`、`scenarios.yaml`、Router prompt 和 examples。
3. `nodes/router/signals.py` 与 `rules.py` 只负责 rule fallback，不是正常路径的语义权威。
4. 新 intent 需要同步检查 `IntentName`、policy、compiler、validator 和 benchmark。
5. 用 trace 确认 router 的 evidence/reason 可读，而不只是 intent 正确。

## 新增稳定工作流

稳定、高频、工具链固定的问题适合 workflow template。开放问题应先走 generic。

检查：

- 所有工具已注册。
- source tool 产物能被后续工具消费。
- count/list/rank/evidence 共用正确候选池。
- template 路径不应出现 planner。

## 新增只读工具

1. 在 `resume_query_ai_qa/tools/` 或 `resume_query_tools/` 实现只读能力。
2. 注册到 `tools/registry.py`。
3. 在 `tool_policy.yaml` 声明工具能力与允许场景。
4. compiler 绑定参数，validator 校验参数和产物 lineage。
5. aggregator 只消费结果，不直接调用工具。

禁止：工具生成最终答案、写数据底座、绕过 DTO 返回任意对象。

## 修改答案结构

优先改 YAML，不要在前端补事实。

- `aggregator_tasks.yaml`：问题属于什么回答任务、自由度如何。
- `answer_layouts.yaml`：章节、标题、写作规则和硬约束。
- renderer：只有 YAML 无法表达时才修改。
- answer validator：确保新结构仍然校验 facts/claims/evidence。

## 修改校验规则

Validator 应严格拦事实漂移，但应区分“事实错误”和“表达格式变化”。

每次修改至少覆盖：

- 一个合法输入。
- 一个真实越界输入。
- 一个容易误伤的边界输入。
- fallback/repair 后仍重新进入 validator。

## 如何选择测试

| 改动层 | 最小回归 |
| --- | --- |
| router / context | `run_policy_contract_benchmark.py`、`run_policy_contract_benchmark.py` |
| compiler / workflow | `run_plan_contract_benchmark.py`、`run_plan_contract_benchmark.py` |
| tool / execution | `run_runtime_contract_benchmark.py`、`run_runtime_contract_benchmark.py` |
| aggregator / answer | `run_runtime_contract_benchmark.py`、`run_runtime_contract_benchmark.py` |
| repair / fallback | `run_runtime_contract_benchmark.py`、`run_runtime_contract_benchmark.py` |
| 结构 / 文档 / 日志 | `run_runtime_contract_benchmark.py`、`run_runtime_contract_benchmark.py` |

跨层修改最后运行：

```bash
./.venv/bin/python resume_query_ai_qa/benchmarks/run_plan_contract_benchmark.py
./.venv/bin/python resume_query_ai_qa/benchmarks/run_plan_contract_benchmark.py
```

## Review 清单

- 修改是否落在真正拥有该职责的层？
- 是否改变了现有 API、工具参数或业务语义？
- 新行为是否能从 trace 看懂？
- 错误是否包含层级、原因和建议检查入口？
- 是否补了合法、越界和误伤边界测试？
- 文档中的 source of truth 是否同步？
