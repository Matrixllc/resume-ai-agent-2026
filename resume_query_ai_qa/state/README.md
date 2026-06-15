# State Package

## 一句话

`resume_query_ai_qa/state/` 是 Query-AI 的运行状态辅助包。

它只负责两件事：

```text
trace.py           = 运行 trace / node decision / route decision / snapshot / error 事件
session_context.py = final 阶段构建下一轮 session_context
```

它不做业务判断，不调用工具，不生成答案。

## 架构位置

```text
graph runner/nodes/routes
-> state helpers
-> qa.trace / updated_session_context / observability events
```

典型调用：

```text
runner.run
-> record_run_start
-> graph adapters log_decision
-> record_node_decision
-> routes.record_route_decision
-> final_node
-> build_updated_session_context
-> finalize_run_trace
```

## 它做什么

```text
记录 run_start / run_end / run_error
记录每个 node 的 decision log
记录 route decision
深度调试时记录 state snapshot
把本轮结果整理成下一轮可用的 session_context
调用 observability.emit_event 发出结构化事件
```

## 它不做什么

```text
不决定 graph 下一跳
不判断 intent / scenario
不修复 plan / execution / answer
不调用 tools
不查询数据库或向量库
不生成业务答案
不改变 tool result 事实
```

## 文件职责

| 文件 | 职责 | 谁调用 |
| --- | --- | --- |
| `trace.py` | 记录 run/node/route/snapshot/error 事件，写入 `qa.trace` 并发 observability event。 | `graph/runner.py`、`graph/trace_logging.py`、`graph/routes.py` |
| `session_context.py` | 在 final 阶段从 `ResumeQAState` 构建下一轮 `updated_session_context`。 | `graph/terminal_nodes.py` |
| `__init__.py` | 稳定公开导出入口。 | graph 和其他上层调用方 |

## trace.py

职责：

```text
把 graph 运行过程写成可诊断的事件流。
```

核心函数：

| 函数 | 什么时候调用 | 写入什么 |
| --- | --- | --- |
| `record_run_start` | `runner.run` 开始时 | `run_start` observability event |
| `record_node_decision` | 每个 graph adapter 完成时 | `qa.trace.decision_log`、`qa.trace.node_events` |
| `record_route_decision` | 条件边选择下一跳时 | `qa.trace.route_events` |
| `record_state_snapshot` | deep debug 开启时 | `qa.trace.state_snapshots` |
| `finalize_run_trace` | graph 结束后 | `qa.trace.run_summary`、`run_end` event |
| `record_run_error` | graph invoke 抛出未吸收异常时 | `run_error` event |

注意：

```text
trace.py 只记录发生了什么，不重新判断对错。
```

## session_context.py

职责：

```text
把本轮最终状态整理成下一轮可以解析上下文指代的 session_context。
```

核心函数：

```text
build_updated_session_context(qa)
```

输入：

```text
ResumeQAState
```

输出：

```text
dict[str, Any]
```

写入字段包括：

```text
last_turn_id
last_user_question
last_intent
last_conditions
last_normalized_conditions
last_answer_summary
last_ranking_candidate_ids / names
last_comparison_candidate_ids / names
last_candidate_pool_ids / names
last_candidate_id / name
last_jd_criteria
```

注意：

```text
这里只在 final 阶段构建下一轮上下文，不影响当前轮答案。
构建后会经过 sanitize_session_context，避免把不该进入 session 的数据带到下一轮。
```

## 工具结果到上下文的映射

| ToolResult.tool_name | 写入 session_context |
| --- | --- |
| `rank_candidates` | `last_ranking_candidate_ids`、`last_ranking_candidate_names`、`last_candidate_id`、`last_candidate_name` |
| `build_comparison_pack` | `last_comparison_candidate_ids`、`last_comparison_candidate_names`、`last_candidate_id`、`last_candidate_name` |
| `get_candidate_profile_intro` | `last_candidate_id`、`last_candidate_name` |
| `get_candidate_profiles_intro` | 第一位 profile 作为 `last_candidate_id/name` |
| `filter_candidates` | `last_candidate_pool_ids`、`last_candidate_pool_names`、`last_candidate_id` |
| `hybrid_search_candidates` | `last_candidate_pool_ids`、`last_candidate_pool_names`、`last_candidate_id` |
| `list_all_candidates` | `last_candidate_pool_ids`、`last_candidate_pool_names`、`last_candidate_id` |
| `load_default_jd_criteria` | `last_jd_criteria` |
| `load_general_resume_criteria` | `last_jd_criteria` |
| `extract_jd_criteria` | `last_jd_criteria` |

## 和 graph 的边界

Graph 负责：

```text
什么时候调用 state helpers
把 state helpers 的结果写回 qa
```

State 负责：

```text
如何记录 trace event
如何构建 updated_session_context
```

State 不负责：

```text
判断 route
决定 repair/fallback
解释 validator errors
```

## 和 nodes/core 的边界

Node/core 负责业务判断：

```text
router 判断 intent
validator 判断错误
repair 判断是否可修
aggregator 生成答案
```

State 只记录和交接：

```text
把 node 输出写成 trace
把最终状态写成下一轮 session_context
```

## 阅读顺序

```text
1. README.md
2. STATE_FLOW.md
3. trace.py
4. session_context.py
5. __init__.py
```

## 是否需要拆分

不需要。

原因：

```text
trace.py 只负责 trace event mutation，职责单一。
session_context.py 只负责 terminal session context handoff，职责单一。
目录没有 graph/nodes.py 那种超长 adapter 混杂问题。
强行拆分会增加跳转，不会提升阅读性。
```

## 验收

```bash
rg "State Package|STATE_FLOW|record_node_decision|record_route_decision|build_updated_session_context|last_candidate_pool_ids" resume_query_ai_qa/state
./.venv/bin/python -m compileall -q resume_query_ai_qa/state
./.venv/bin/python resume_query_ai_qa/benchmarks/run_policy_contract_benchmark.py
./.venv/bin/python resume_query_ai_qa/benchmarks/run_plan_contract_benchmark.py
./.venv/bin/python resume_query_ai_qa/benchmarks/run_runtime_contract_benchmark.py
```
