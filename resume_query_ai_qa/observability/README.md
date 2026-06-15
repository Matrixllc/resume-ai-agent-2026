# Observability Package

`observability` 是 Query-AI 的结构化日志输出层。

一句话：

```text
state.trace 负责记录发生了什么
observability 负责把这些事件和 trace 摘要安全落盘
```

它不参与业务决策，不修改 graph state，不判断 plan / execution / answer 是否正确。

## 架构位置

```text
graph runner / graph nodes / graph routes
-> state.trace
-> observability.emit_event / write_run_log
-> logs/query_ai_events.jsonl / qa_runs.jsonl / <timestamp>_<trace_id>.json
```

更具体地说：

```text
runner.run
-> record_run_start
-> record_node_decision / record_route_decision / record_state_snapshot
-> finalize_run_trace
-> write_run_log
```

`state/trace.py` 决定“什么时候记录、写入 qa.trace 的哪些字段”。  
`observability/logging.py` 决定“怎么序列化、怎么压缩、写到哪些日志文件”。

## 它做什么

- 配置 Loguru sink，写入 `logs/query_ai_events.jsonl`。
- 输出结构化事件：run start/end、node end、route decision、state snapshot、run error。
- 写每轮查询摘要：`logs/qa_runs.jsonl`。
- 写单轮诊断详情：`logs/<timestamp>_<trace_id>.json`。
- 把大对象压缩成诊断摘要，例如工具结果形态、答案长度、错误位置、上下文变化。

## 它不做什么

- 不决定 graph route。
- 不选择 node、tool、workflow。
- 不修改 `qa.trace` 里的事件结构。
- 不判断 plan / execution / answer 是否正确。
- 不修复 plan、工具结果或答案。
- 不读取业务 YAML 做决策。

## 输出文件

| 文件 | 内容 | 用途 |
| --- | --- | --- |
| `query_ai_events.jsonl` | 原子事件流 | 追实时运行、tail 行为 |
| `qa_runs.jsonl` | 每轮查询一行摘要 | 快速按 `trace_id` 找问题 |
| `<timestamp>_<trace_id>.json` | 单轮详细诊断 | 排查节点输出、路由、失败原因、答案摘要、上下文变化 |

## 文件职责

| 文件 | 职责 | 阅读入口 |
| --- | --- | --- |
| `logging.py` | Loguru sink、事件发送、run log 落盘、摘要压缩 | `configure_query_ai_logging` -> `emit_event` -> `write_run_log` |
| `__init__.py` | 稳定导出观测入口 | `configure_query_ai_logging`, `emit_event`, `write_run_log` |

## 和 State 的边界

`state/trace.py`：

- 写 `qa.trace.decision_log`
- 写 `qa.trace.route_events`
- 写 `qa.trace.state_snapshots`
- 设置 `qa.trace.run_summary`
- 调用 `emit_event`

`observability/logging.py`：

- 不决定 trace 内容
- 不改变业务状态
- 把 trace 和事件转成 JSON 安全格式
- 把运行摘要和诊断详情写入 `logs/`

## YAML 关系

`observability` 当前不直接读取业务 YAML。

它只通过 `ResumeQAConfig` 使用：

- `config.app_root`：确定 `logs/` 输出目录。
- trace/debug 相关状态：来自运行中的 `qa.trace`，不是这里重新判断。

所以本目录不需要单独的 `YAML_USAGE.md`。强行写会让读者误以为 observability 也参与业务规则决策。

## 阅读顺序

1. [README.md](README.md)
2. [OBSERVABILITY_FLOW.md](OBSERVABILITY_FLOW.md)
3. [logging.py](logging.py)
4. [../state/README.md](../state/README.md)
5. [../state/STATE_FLOW.md](../state/STATE_FLOW.md)

## 验收

```bash
rg "Observability Package|OBSERVABILITY_FLOW|configure_query_ai_logging|emit_event|write_run_log|query_ai_events" resume_query_ai_qa/observability
./.venv/bin/python -m compileall -q resume_query_ai_qa/observability
./.venv/bin/python resume_query_ai_qa/benchmarks/run_policy_contract_benchmark.py
./.venv/bin/python resume_query_ai_qa/benchmarks/run_plan_contract_benchmark.py
./.venv/bin/python resume_query_ai_qa/benchmarks/run_runtime_contract_benchmark.py
```
