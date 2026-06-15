# Graph Flow

## 阅读目标

这份文档讲 graph 层怎么从一次 `run()` 走到最终 `ResumeQAState`。

Graph 层只做编排：

```text
初始化 state
注册节点和边
调用 nodes/* API
根据 state 选择下一跳
记录 trace
收口 final / clarification / fail
```

业务细节看 `nodes/` 和 `core/`，不要在 graph 里找 intent、tool policy、answer layout 的完整规则。

## 1. Public Entry

### `runner.run(...)`

入口：

```text
resume_query_ai_qa/graph/runner.py
```

输入：

```text
question
session_context
use_llm
max_plan_repairs
max_execution_repairs
max_answer_rewrites
debug_trace
config
```

执行过程：

```text
load_config
-> configure_query_ai_logging
-> build_state_graph
-> build_initial_state
-> record_run_start
-> graph.invoke
-> finalize_run_trace
-> write_run_log
-> ResumeQAState
```

注意：

```text
retry 上限来自 run() 参数写入 state。
routes.py 用 state 中的 max_* 判断是否还能 repair/rewrite。
```

## 2. State 初始化

### `build_initial_state(...)`

位置：

```text
graph/state.py
```

初始写入：

```text
qa = ResumeQAState(question, session_context)
config
use_llm
max_plan_repairs
max_execution_repairs
max_answer_rewrites
plan_repairs = 0
execution_repairs = 0
answer_rewrites = 0
final_status = pending
```

还没有：

```text
router_output
execution_decision
semantic_plan
qa.plan
qa.tool_results
qa.answer
current_*_errors
```

这些字段由后续节点逐步写入。

## 3. Graph 拓扑

### `build_state_graph()`

位置：

```text
graph/build.py
```

普通边：

```text
START -> router
router -> condition_normalizer
condition_normalizer -> execution_policy
planner -> plan_compiler
plan_compiler -> plan_validator
plan_repair -> plan_validator
executor -> execution_validator
execution_repair -> plan_validator
aggregator -> answer_validator
answer_rewrite -> answer_validator
rule_answer_fallback -> answer_validator
final -> END
clarification -> END
fail -> END
```

条件边：

```text
execution_policy -> template/generic
plan_validator -> execute/repair/clarify/fail
execution_validator -> aggregate/repair/clarify/fail
answer_validator -> final/rewrite/fallback/fail
```

## 4. 正常成功路径

```text
router
-> condition_normalizer
-> execution_policy
-> planner? / plan_compiler
-> plan_validator
-> executor
-> execution_validator
-> aggregator
-> answer_validator
-> final
```

### `router_node`

文件：

```text
graph/query_nodes.py
```

调用：

```text
route_question_llm 或 route_question
```

读：

```text
qa.question
use_llm
config
```

写：

```text
qa.intent
qa.trace.router_output
state.router_output
state.last_decision_meta
```

判断：

```text
use_llm and is_llm_enabled(config)
```

YAML：

```text
graph 不解释 YAML；router 内部读 intents/scenarios/router_rules 等。
```

### `condition_normalizer_node`

调用：

```text
normalize_router_output
```

读：

```text
state.router_output
qa.question
```

写：

```text
state.router_output
qa.trace.router_output
```

判断：

```text
无 route 判断；只是覆盖 RouterOutput 中的 normalized_conditions。
```

### `execution_policy_node`

调用：

```text
resolve_execution_policy
```

读：

```text
qa.question
state.router_output
config
```

写：

```text
state.execution_decision
qa.trace.execution_decision
```

下一跳：

```text
routes.route_after_execution_policy_node
```

### `planner_node`

只在 generic 路径运行。

调用：

```text
resolve_semantic_plan
```

读：

```text
qa.question
state.router_output
state.execution_decision
use_llm
config
```

写：

```text
state.semantic_plan
qa.trace.semantic_plan
```

### `plan_compiler_node`

调用：

```text
compile_semantic_plan_with_meta
```

读：

```text
qa.question
state.router_output
state.semantic_plan 或 semantic_plan_from_router(...)
state.execution_decision
current_session_context(state)
config
```

写：

```text
qa.plan
qa.sub_tasks
qa.trace.planner_output
state.last_decision_meta
```

注意：

```text
template 路径没有 planner_node，compiler 会用 semantic_plan_from_router 生成最小 SemanticPlan。
```

### `plan_validator_node`

调用：

```text
validate_plan
```

读：

```text
qa.plan
state.router_output
current_session_context(state)
config
```

写：

```text
qa.plan_errors
qa.trace.plan_validation_errors
state.plan_validation_ok
state.current_plan_errors
state.current_plan_issues
```

下一跳：

```text
routes.route_after_plan_validation
```

### `executor_node`

调用：

```text
execute_plan_with_context
```

读：

```text
qa.plan
current_session_context(state)
config
```

写：

```text
qa.tool_results
qa.trace.tool_calls
qa.trace.tool_results_summary
```

注意：

```text
工具失败被 executor 包装成 failed ToolResult，后面由 execution_validator 判断。
```

### `execution_validator_node`

调用：

```text
validate_execution
```

读：

```text
qa.plan
qa.tool_results
state.router_output
current_session_context(state)
config
```

写：

```text
qa.execution_errors
qa.trace.execution_validation_errors
state.execution_validation_ok
state.current_execution_errors
state.current_execution_issues
```

下一跳：

```text
routes.route_after_execution_validation
```

### `aggregator_node`

调用：

```text
aggregate_answer_with_meta
```

读：

```text
qa.question
qa.plan
qa.tool_results
state.execution_decision
state.router_output
use_llm
config
```

写：

```text
qa.answer
qa.trace.aggregator_answer
state.last_decision_meta
```

注意：

```text
answer 文本可以来自 LLM，但 claims/evidence refs 由 grounded 收口。
```

### `answer_validator_node`

调用：

```text
validate_answer
```

读：

```text
qa.answer
qa.tool_results
qa.plan
config
```

写：

```text
qa.answer_errors
qa.trace.answer_validation_errors
state.answer_validation_ok
state.current_answer_errors
state.current_answer_issues
```

下一跳：

```text
routes.route_after_answer_validation
```

### `final_node`

调用：

```text
build_updated_session_context
```

读：

```text
qa
```

写：

```text
qa.updated_session_context
qa.trace.updated_session_context
state.final_status = ok
```

## 5. Route 判断详解

### execution_policy route

```text
if decision.compiler == workflow_template:
    template -> plan_compiler
else:
    generic -> planner
```

判断来源：

```text
ExecutionDecision.compiler
```

### plan validation route

```text
if plan_validation_ok:
    execute
else:
    decision = classify_plan_repair_action(...)
    clarify / fail / repair
    repair 还要检查 plan_repairs < max_plan_repairs
```

判断来源：

```text
plan_validator 输出
plan_repair classify
graph retry state
```

### execution validation route

```text
if execution_validation_ok:
    aggregate
else:
    decision = classify_execution_repair_action(...)
    clarify / fail / repair
    repair 还要检查 execution_repairs < max_execution_repairs
```

判断来源：

```text
execution_validator 输出
execution_repair classify
graph retry state
```

### answer validation route

```text
if answer_validation_ok:
    final
elif answer_fallback_requested:
    fallback
elif answer_rewrites < max_answer_rewrites:
    rewrite
elif answer_rewrites == max_answer_rewrites:
    fallback
else:
    fail
```

判断来源：

```text
answer_validator 输出
answer_rewrite fallback flag
graph rewrite count
```

## 6. Plan / Execution Repair 路径

### Plan repair

```text
plan_validator
-> route_after_plan_validation
-> plan_repair
-> plan_validator
```

`plan_repair_node` 写：

```text
qa.plan
state.plan_repairs += 1
qa.retry_count.planner += 1
```

为什么回 validator：

```text
repair 生成的新 QueryPlan 仍然必须通过同一套执行前合同检查。
```

### Execution repair

```text
execution_validator
-> route_after_execution_validation
-> execution_repair
-> plan_validator
-> executor
```

`execution_repair_node` 写：

```text
qa.plan
state.execution_repairs += 1
qa.retry_count.planner += 1
```

为什么回 plan_validator：

```text
execution repair 会修改 QueryPlan，因此必须先重新校验 plan，再重新执行。
```

## 7. Answer Rewrite / Fallback 路径

### Answer rewrite

```text
answer_validator
-> route_after_answer_validation
-> answer_rewrite
-> answer_validator
```

`answer_rewrite_node` 写：

```text
state.answer_rewrites += 1
qa.retry_count.aggregator_rewrite += 1
qa.answer            # 如果 rewrite candidate 存在
state.answer_fallback_requested
```

为什么回 validator：

```text
rewrite 只生成候选答案，不能直接 final。
```

### Rule answer fallback

```text
answer_validator
-> route_after_answer_validation
-> rule_answer_fallback
-> answer_validator
```

`rule_answer_fallback_node` 写：

```text
qa.answer
state.answer_rewrites += 1
state.answer_fallback_requested = False
```

为什么回 validator：

```text
确定性答案也必须满足 answer_validator 的 count/ranking/evidence/layout/privacy 合同。
```

## 8. Terminal 路径

### Clarification

```text
plan_validator / execution_validator
-> clarification
-> END
```

写：

```text
qa.clarification_required = True
qa.clarification_question
qa.clarification_options
qa.answer = clarification question
state.final_status = needs_clarification
```

### Fail

```text
plan_validator / execution_validator / answer_validator
-> fail
-> END
```

写：

```text
state.final_status = failed
trace 中保留 plan/execution/answer errors
```

## 9. YAML 怎么参与 graph

Graph 自己不直接解释 YAML 业务字段。

它做：

```text
runner 加载 config
state 持有 config
adapter 把 config 传给 node package
routes 用 node classify 结果和 retry state 判断下一跳
```

真正用 YAML 的地方：

```text
router / condition_normalizer / execution_policy / planner / compiler / validators / repair / aggregator / answer
```

retry 注意点：

```text
run(max_plan_repairs=2, max_execution_repairs=2, max_answer_rewrites=1)
```

这些参数进入 state，routes 读 state。`validation.yaml.retry_limits` 是配置合同和诊断参考，不是 routes.py 直接读取的字段。

## 10. 排查入口

```text
graph 没走预期节点       -> build.py / routes.py
state 字段没传下去       -> state.py / 对应 *_nodes.py
某节点 output 不对        -> nodes/<node>/README.md
repair 次数不对          -> runner.py 参数 / state.py / routes.py
trace 缺字段             -> trace_logging.py / 对应 adapter
final_status 不对        -> terminal_nodes.py / routes.py
```

## 11. 验收命令

```bash
rg "Graph Package|GRAPH_FLOW|runner.run|build_state_graph|route_after_answer_validation|router_node|answer_rewrite_node" resume_query_ai_qa/graph
./.venv/bin/python -m compileall -q resume_query_ai_qa/graph
./.venv/bin/python resume_query_ai_qa/benchmarks/run_policy_contract_benchmark.py
./.venv/bin/python resume_query_ai_qa/benchmarks/run_plan_contract_benchmark.py
./.venv/bin/python resume_query_ai_qa/benchmarks/run_runtime_contract_benchmark.py
./.venv/bin/python resume_query_ai_qa/benchmarks/run_architecture_contract_benchmark.py
```
