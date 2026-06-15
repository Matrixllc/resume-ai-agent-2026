# Observability Flow

这份文档只讲 `observability` 怎么被调用、怎么落盘。  
业务事件什么时候发生，由 `state/trace.py` 和 graph 节点决定。

## 1. 总调用链

```text
runner.run
-> configure_query_ai_logging
-> state.record_run_start
-> emit_event("run_start")
-> graph nodes / graph routes
-> state.record_node_decision / record_route_decision / record_state_snapshot
-> emit_event(...)
-> state.finalize_run_trace
-> emit_event("run_end")
-> write_run_log
```

读代码时建议先看 `state/trace.py`，再看 `observability/logging.py`：

```text
state.trace = 事件生产者和 qa.trace mutation
observability.logging = 事件序列化和日志落盘
```

## 2. 实时事件流

入口：

```text
emit_event(kind, config=config, **fields)
```

执行过程：

```text
emit_event
-> configure_query_ai_logging
-> _safe_payload
-> logger.bind(...).info(kind)
-> data/logs/query_ai/query_ai_events.jsonl
```

关键点：

- `config` 存在时会确保 Loguru sink 已配置。
- `_safe_payload` 用 JSON round-trip 把 Pydantic、datetime、异常等对象转成可写 JSON 的形态。
- `emit_event` 不写 `qa.trace`，它只负责发日志。

## 3. Loguru Sink 配置

入口：

```text
configure_query_ai_logging(config)
```

执行过程：

```text
config.logs_dir
-> data/logs/query_ai/query_ai_events.jsonl
-> logger.add(... serialize=True ...)
```

输出策略：

- 文件：`query_ai_events.jsonl`
- 格式：Loguru serialized JSON
- rotation：`20 MB`
- retention：`14 days`
- 同一个 sink 只注册一次

## 4. Run Log 落盘

入口：

```text
write_run_log(qa, config)
```

执行过程：

```text
write_run_log
-> configure_query_ai_logging
-> _compact_run_summary
-> qa.trace.run_summary = summary
-> _failed_at
-> _compact_final_answer
-> _context_delta
-> append data/logs/query_ai/qa_runs.jsonl
-> write data/logs/query_ai/<timestamp>_<trace_id>.json
```

当前详细 JSON 包含：

```text
run_summary
decision_log
route_events
failed_at
final_answer
context_delta
node_events          # deep_debug 时写入
state_snapshots      # deep_debug 时写入
```

注意：`_compact_node_steps`、`_execution_path`、`_node_timeline` 是现有诊断摘要 helper，但当前 `write_run_log()` 没有把它们写入 detail。它们可以作为后续增强运行诊断视图的候选入口。

## 5. 摘要压缩

`_compact_run_summary()` 生成 `qa_runs.jsonl` 的一行摘要：

```text
question
intent
final_status
clarification_required
engines_by_node
tool_result_status
validation_errors_count
path_preview
failed_at_node
failed_reason
answer_preview
```

它的目标是“快速定位一轮 run”，不是完整还原执行细节。

## 6. 失败定位

`_failed_at()` 只在最终状态是下面两类时返回内容：

```text
failed
needs_clarification
```

它从最后一个 route 和最后一个 node output 中提取：

```text
node
route_from
route_to
reason
errors
```

它不重新判断失败原因，只整理已有 trace 里的结论。

## 7. 工具结果摘要

`_tool_result_status()` 和 `_executor_tool_details()` 会把工具结果压缩成：

```text
tool
status
result_shape
result_count
error
warnings
output_key
```

这样日志能看出“哪个工具失败、结果大概是什么形状”，但不会把大 payload 全量塞进摘要。

## 8. 答案和上下文摘要

`_compact_final_answer()` 输出：

```text
answer_length
claim_count
claim_types
used_evidence_count
warnings
```

`_context_delta()` 对比：

```text
qa.session_context
qa.updated_session_context
```

只记录本轮结束后新增或变化的上下文字段。

## 9. 排查怎么读

实时看运行：

```text
data/logs/query_ai/query_ai_events.jsonl
```

找某轮 trace：

```text
data/logs/query_ai/qa_runs.jsonl
```

看某轮为什么失败：

```text
data/logs/query_ai/<timestamp>_<trace_id>.json
-> failed_at
-> decision_log
-> route_events
```

看业务字段为什么变了：

```text
state/STATE_FLOW.md
-> record_node_decision / record_route_decision
-> graph/*_nodes.py
```

## 10. 边界提醒

`observability` 只做可观测性，不做业务纠偏。

如果发现：

- intent 错：看 `nodes/router`
- plan 错：看 `nodes/plan_compiler` / `nodes/plan_validator`
- 工具失败：看 `nodes/executor` / `nodes/execution_validator`
- 答案乱：看 `nodes/aggregator` / `nodes/answer_validator`
- trace 字段没记录：看 `state/trace.py`
- 日志没落盘：看 `observability/logging.py`
