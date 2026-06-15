# State Flow

## 阅读目标

这份文档讲 `state` 包的两条流：

```text
1. trace event flow
2. session context handoff flow
```

`state` 不参与业务判断。它只负责记录和交接。

## 1. Trace Event Flow

完整阅读线：

```text
runner.run
-> record_run_start
-> graph trace_logging.log_decision
-> record_node_decision
-> routes.record_route_decision
-> record_state_snapshot
-> finalize_run_trace
-> record_run_error
```

## 2. `record_run_start`

调用位置：

```text
graph/runner.py
```

什么时候：

```text
graph.invoke 之前
```

写什么：

```text
trace_id
event_type = run_start
question
session_context_keys
created_at
```

去哪里：

```text
observability.emit_event("run_start", ...)
```

注意：

```text
它不写 qa.trace.decision_log，只发 run_start 事件。
```

## 3. `record_node_decision`

调用位置：

```text
graph/trace_logging.py
```

graph adapter 通常这样调用：

```text
log_decision(...)
-> record_node_decision(...)
```

什么时候：

```text
每个 graph node adapter 完成后
```

写什么：

```text
qa.trace.decision_log[]
qa.trace.node_events[]
observability node_end event
deep_debug 时额外写 node_start event
```

核心字段：

```text
step
node
engine
fallback_reason
summary
output
debug
llm
duration_ms
```

summary 从哪里来：

```text
调用方传 summary
或 _node_summary(node, output) 自动生成
```

注意：

```text
record_node_decision 只记录节点输出摘要，不判断输出是否正确。
validator 是否 ok、route 去哪里，都不在这里决定。
```

## 4. `record_route_decision`

调用位置：

```text
graph/routes.py
```

什么时候：

```text
条件边选择下一跳时
```

写什么：

```text
qa.trace.route_events[]
```

字段：

```text
trace_id
event_type = route_decision
step
route_from
route_to
reason
errors
retry_count
created_at
```

什么时候发 observability event：

```text
route_to in {"repair", "fallback", "clarify", "fail"}
```

注意：

```text
record_route_decision 不决定 route。
route 已经由 graph/routes.py 判断完成，它只记录判断结果。
```

## 5. `record_state_snapshot`

调用位置：

```text
graph/trace_logging.py
```

触发条件：

```text
qa.trace.deep_debug = True
```

写什么：

```text
qa.trace.state_snapshots[]
observability state_snapshot event
```

summary 包含：

```text
intent
has_plan
tool_results count
has_answer
plan_errors count
execution_errors count
answer_errors count
clarification_required
```

注意：

```text
snapshot 是轻量定位，不保存完整 graph state。
```

## 6. `finalize_run_trace`

调用位置：

```text
graph/runner.py
```

什么时候：

```text
graph.invoke 正常返回后
```

写什么：

```text
qa.trace.run_summary
observability run_end event
```

summary 包含：

```text
trace_id
event_type = run_end
final_status
node_count
route_count
state_snapshot_count
created_at
```

注意：

```text
final_status 已由 graph terminal node 和 runner 收口。
finalize_run_trace 不重新判断成功/失败。
```

## 7. `record_run_error`

调用位置：

```text
graph/runner.py
```

什么时候：

```text
graph.invoke 抛出未被业务流程吸收的异常
```

写什么：

```text
observability run_error event
```

字段：

```text
trace_id
error_type
error
created_at
```

注意：

```text
业务上的 plan/execution/answer validation error 不走这里。
只有未被 graph 捕获的异常才走 record_run_error。
```

## 8. Session Context Handoff Flow

完整阅读线：

```text
graph/terminal_nodes.final_node
-> build_updated_session_context
-> scan qa.trace / qa.answer / qa.tool_results
-> sanitize_session_context
-> qa.updated_session_context
```

## 9. `build_updated_session_context`

调用位置：

```text
graph/terminal_nodes.py final_node
```

什么时候：

```text
最终答案通过 answer_validator，进入 final_node 时
```

输入：

```text
ResumeQAState qa
```

输出：

```text
dict[str, Any]
```

写入：

```text
qa.updated_session_context
qa.trace.updated_session_context
```

## 10. 基础上下文字段

不依赖工具结果，直接来自 QA state：

```text
last_turn_id              <- qa.trace.trace_id
last_user_question        <- qa.question[:300]
last_intent               <- qa.intent
last_conditions           <- qa.trace.router_output.conditions
last_normalized_conditions<- qa.trace.router_output.normalized_conditions
last_answer_summary       <- qa.answer.answer[:200]
```

用途：

```text
下一轮可以知道上一轮问了什么、答了什么、筛选条件是什么。
```

## 11. `rank_candidates` 映射

成功工具：

```text
rank_candidates
```

写入：

```text
last_ranking_candidate_ids
last_ranking_candidate_names
last_candidate_id
last_candidate_name
```

用途：

```text
支持“第一名是谁”“第一名有哪些项目”“刚才排名里的人”等后续问题。
```

## 12. `build_comparison_pack` 映射

成功工具：

```text
build_comparison_pack
```

写入：

```text
last_comparison_candidate_ids
last_comparison_candidate_names
last_candidate_id
last_candidate_name
```

用途：

```text
支持“这两个人”“刚才比较的候选人”等后续问题。
```

## 13. Profile 工具映射

成功工具：

```text
get_candidate_profile_intro
get_candidate_profiles_intro
```

写入：

```text
last_candidate_id
last_candidate_name
```

注意：

```text
get_candidate_profiles_intro 只取 profiles[0] 作为 last_candidate。
```

用途：

```text
支持“这个人/刚才那个人”的单候选追问。
```

## 14. 候选人池工具映射

成功工具：

```text
filter_candidates
hybrid_search_candidates
list_all_candidates
```

写入：

```text
last_candidate_pool_ids
last_candidate_pool_names
last_candidate_id
```

提取逻辑：

```text
_candidate_ids_from_tool_data
_candidate_names_from_tool_data
```

用途：

```text
支持“这些人”“刚才筛出来的人”“这个集合里谁更强”等后续问题。
```

## 15. JD Criteria 映射

成功工具：

```text
load_default_jd_criteria
load_general_resume_criteria
extract_jd_criteria
```

写入：

```text
last_jd_criteria
```

用途：

```text
支持下一轮继续沿用岗位/JD 标准。
```

## 16. sanitize

最后一步：

```text
sanitize_session_context(context)
```

位置：

```text
core.rules.session_context
```

作用：

```text
清理 session_context，限制可进入下一轮的字段和值。
```

注意：

```text
state/session_context.py 负责构建候选 context。
sanitize_session_context 负责最终安全收口。
```

## 17. 当前不做什么

`state` 不会：

```text
从失败工具结果写上下文
把证据全文写入 session_context
把所有 profile 写成上下文
把 answer validator 错误解释成 route
在当前轮中反向影响 router/planner/executor
```

## 18. 排查入口

```text
decision_log 少节点      -> trace.py record_node_decision / graph adapter log_decision
route_events 少记录      -> trace.py record_route_decision / graph routes.py
deep_debug 没快照        -> trace.py record_state_snapshot / qa.trace.deep_debug
updated_session_context 缺候选池 -> session_context.py candidate pool tools
“第一名”追问失败        -> rank_candidates 是否写入 last_ranking_candidate_ids
“这些人”追问失败        -> filter/hybrid/list 是否写入 last_candidate_pool_ids
JD 沿用失败             -> criteria tools 是否写入 last_jd_criteria
```

## 19. 验收命令

```bash
rg "State Package|STATE_FLOW|record_node_decision|record_route_decision|build_updated_session_context|last_candidate_pool_ids" resume_query_ai_qa/state
./.venv/bin/python -m compileall -q resume_query_ai_qa/state
./.venv/bin/python resume_query_ai_qa/benchmarks/run_policy_contract_benchmark.py
./.venv/bin/python resume_query_ai_qa/benchmarks/run_plan_contract_benchmark.py
./.venv/bin/python resume_query_ai_qa/benchmarks/run_runtime_contract_benchmark.py
```
