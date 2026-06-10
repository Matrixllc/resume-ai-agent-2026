# Query-AI 日志操作手册

这份手册用于排查 `resume_query_ai_qa` 一次问答为什么成功、失败、进入 repair、
fallback 或正常空证据回答。日志只记录 QA graph 的运行轨迹，不改变运行行为。

## 主链路

```text
router
-> condition_normalizer
-> execution_policy
   -> template: plan_compiler
   -> generic: planner -> plan_compiler
-> plan_validator
   -> ok: executor
   -> repair: plan_repair -> plan_validator
   -> clarify: clarification
   -> fail: fail
-> executor
-> execution_validator
   -> ok: aggregator
   -> repair: execution_repair -> plan_validator
   -> clarify: clarification
   -> fail: fail
-> aggregator
-> answer_validator
   -> ok: final
   -> rewrite: answer_rewrite -> answer_validator
   -> fallback: rule_answer_fallback -> answer_validator
   -> fail: fail
```

关键契约：

- API 默认返回最小 `trace.diagnosis`；`debug=true` 才返回完整 trace 摘要和日志定位。
- `execution_repair` 后回 `plan_validator`，不回 `plan_compiler`。
- `executor` 只执行工具和内部异常 retry；业务错误、contract 错误由 validator 分类。
- 工具正常返回 0 条证据是可回答结果，记录 `empty_evidence` warning，不触发
  `execution_repair`，也不把 query 改空再查。
- `fail` 是不可恢复终点，trace 会保留 plan / execution / answer 三层错误。

## 日志文件

每次 `run()` 结束都会写两个文件到：

```text
resume_query_ai_qa/logs/
```

| 文件 | 用途 |
| --- | --- |
| `qa_runs.jsonl` | 每次运行一行 summary，适合快速筛选失败、按问题找 trace。 |
| `<timestamp>_<trace_id>.json` | 单次运行完整 detail，适合定位具体节点、错误和 fallback。 |

detail JSON 以 `decision_log + route_events` 为唯一事实源：

| 字段 | 看什么 |
| --- | --- |
| `decision_log` | 每个节点唯一的一条完成记录，包含耗时、结果、错误和 fallback/repair。 |
| `route_events` | validator 做出的路由决定。 |
| `failed_at` | 不可恢复失败停在哪个节点。 |
| `aggregator_io_tail` | aggregator / answer_rewrite 的 prompt/response 尾部。 |
| `debug_refs` | semantic plan、compiled plan、answer claims 等排查引用。 |

`query_ai_events.jsonl` 是精简实时事件流，默认只记录 run start/end、node end 和异常路由。
历史日志中的 `execution_path`、`node_timeline`、`node_steps` 仍可由日志 CLI 读取。

## API Trace 摘要

`/qa/ask` 默认返回最小诊断，前端状态卡可直接展示：

| 字段 | 含义 |
| --- | --- |
| `trace.diagnosis.level` | `ok`、`warning`、`error` 等展示级别。 |
| `trace.diagnosis.status` | 最终状态：`ok`、`failed`、`needs_clarification`。 |
| `trace.diagnosis.headline` | 给人看的首要结论。 |
| `trace.diagnosis.impact` | 是否影响最终答案。 |
| `trace.diagnosis.handling` | 系统如何处理问题。 |
| `trace.diagnosis.suggested_check` | 建议优先检查的模块。 |
| `trace.diagnosis.technical_code` | 内部技术原因，供展开详情使用。 |
| `trace.diagnosis.failed_node` | 失败停在哪个节点，成功时为空。 |
| `trace.diagnosis.failed_reason` | 失败原因，例如 `context_missing_not_recoverable`。 |
| `trace.diagnosis.warnings` | 非阻断提示，例如 `empty_evidence`。 |

`debug=true` 时额外返回：

| 字段 | 含义 |
| --- | --- |
| `decision_steps[]` | 每个节点的 `status/summary/errors/warnings/fallback_reason/repair_action/repair_reason/error_category/duration_ms`。 |
| `route_events[]` | validator 路由到 repair/fail/clarify/fallback/final 的原因和重试次数。 |
| `tool_failures[]` | 工具异常或失败结果摘要。 |
| `validation_errors` | plan / execution / answer 三层错误。 |
| `trace_lookup` | detail JSON 位置：`resume_query_ai_qa/logs/<timestamp>_<trace_id>.json`。 |

## 失败字段速查

| 字段 | 产生位置 | 含义 |
| --- | --- | --- |
| `plan_validation_errors` | `plan_validator` | plan 不满足工具、artifact、scenario 或上下文契约。 |
| `execution_validation_errors` | `execution_validator` | 工具结果异常、缺必需对象或违反执行合同。 |
| `answer_validation_errors` | `answer_validator` | 答案 claims、证据、布局、隐私或空证据表达不合格。 |
| `fallback_reason` | 多个节点 | 为什么使用 fallback，例如 LLM 不可用或输出漂移。 |
| `repair_action` | repair 节点 | 实际修复动作，例如 `rule_repair`。 |
| `repair_reason` | repair 节点 | 为什么修复，例如 `semantic_plan_mismatch`。 |
| `error_category` | validator/repair | 错误分类，用于判断能否修复。 |
| `route_reason` | `route_events[]` | validator 为什么路由到下一节点。 |
| `empty_evidence` | execution/answer/diagnosis warning | 工具正常返回 0 条证据，答案应说明未查到证据。 |

## 快速排查顺序

1. 先看前端或 API 的 `diagnosis.headline`。
2. 如果失败，看 `diagnosis.failed_node` 和 `failed_reason`。
3. 如果发生 repair/fallback，看 `route_events[]`。
4. 看对应层的 validator errors：plan、execution、answer。
5. 最后用 `trace_lookup` 打开 detail JSON，查看 `decision_log`、`route_events` 和 `aggregator_io_tail`。

## 常见模式

### 缺上下文

常见错误：

```text
semantic: missing required last_candidate context
semantic: missing required ranking_top context
semantic: missing required comparison_pair context
```

当前策略：

- 普通上下文缺失直接 `failed + context_missing_not_recoverable`。
- 只有明确可澄清的双人比较候选人缺失，才可能进入 `clarification`。

优先看：

- `router.details.context_policy`
- `condition_normalizer.details.context_policy`
- `plan_validator.details.errors`
- `diagnosis.failed_reason`

### Hard Filter 空结果

当前策略：

- 结构化条件问题保持 `hard_filter + filter_candidates`。
- 结果为空时进入 `aggregator`，回答没有符合条件的人。
- 不回退到 hybrid。

优先看：

- `semantic_plan.scenario`
- `debug_refs.compiled_plan.tool_calls`
- `tool_result_status`

### Open Recall 空结果

当前策略：

- 带“可能、相关、类似、找找、看看”等开放召回信号的问题走 `open_recall`。
- 允许使用 `hybrid_search_candidates`。
- 正常空结果仍可回答，没有必要回退到 hard filter。

优先看：

- `router.details.scenario`
- `execution_policy.details.scenarios`
- `plan_validator.details.errors`

### Evidence 空结果

当前策略：

- 候选人解析成功、evidence 工具正常返回 0 条时，最终 `status=ok`。
- 不触发 `execution_repair`，不记录旧式检索回退。
- 答案必须写“未查到相关经历/没有足够证据证明”。
- Debug/trace 中保留 `empty_evidence` 或同等 warning。

优先看：

- `tool_result_status`
- `execution_validator.details.warnings`
- `aggregator.details.insufficient_info_reasons`
- `answer_validator.details.warnings`
- `diagnosis.warnings`

### 工具异常

当前策略：

- executor 做工具异常 retry。
- retry 后仍失败，`execution_validator` 分类为失败。
- 不通过改写 plan 掩盖系统故障。

优先看：

- `executor.details.tools`
- `tool_failures[]`
- `execution_validation_errors`

## Trace 字段与节点

| 节点 | 重点字段 |
| --- | --- |
| `router` | `intent`、`conditions`、`context_policy`、`risk_flags` |
| `condition_normalizer` | 标准化后的条件、context binding、warnings |
| `execution_policy` | `compiler`、`planner`、`workflow_name`、`scenarios` |
| `planner` | `semantic_intent`、`steps`、`tool_hints` |
| `plan_compiler` | `compiler_mode`、`final_tool_calls`、`artifact_bindings`、`hint_tool_decisions` |
| `plan_validator` | `ok`、`errors`、`warnings`、`route_events` |
| `executor` | `tools`、每个 tool 的 status 和 result shape |
| `execution_validator` | `ok`、`errors`、`warnings`、`empty_evidence` |
| `execution_repair` | `repair_action`、`error_category`、`repair_reason`、`previous_errors` |
| `aggregator` | `task_type`、`answer_layout`、`context_summary`、`insufficient_info_reasons` |
| `answer_validator` | `ok`、`errors`、`warnings`、`used_evidence_refs` |
| `answer_rewrite` | `repair_action`、`repair_reason`、`fallback_reason` |
| `fail` | `plan_errors`、`execution_errors`、`answer_errors` |

## 常用命令

```bash
# 人类可读的最近运行
./.venv/bin/python -m resume_query_ai_qa.scripts.query_logs list

# 按 trace_id 查看：发生了什么、系统如何处理、建议检查哪里
./.venv/bin/python -m resume_query_ai_qa.scripts.query_logs show <trace_id>

# 只看失败或 fallback/repair
./.venv/bin/python -m resume_query_ai_qa.scripts.query_logs failures
./.venv/bin/python -m resume_query_ai_qa.scripts.query_logs fallbacks

# 给程序消费的 JSON
./.venv/bin/python -m resume_query_ai_qa.scripts.query_logs show <trace_id> --json

# 最近运行摘要
tail -n 20 resume_query_ai_qa/logs/qa_runs.jsonl

# 根据前端 Trace ID 找 detail
ls resume_query_ai_qa/logs/*<trace_id>*.json

# 格式化查看 detail
python -m json.tool resume_query_ai_qa/logs/<timestamp>_<trace_id>.json | less

# 搜索 repair / fallback
rg -n "fallback_reason|repair_action|repair_reason|route_events" resume_query_ai_qa/logs

# 搜索 validator error
rg -n "plan_validation_errors|execution_validation_errors|answer_validation_errors" resume_query_ai_qa/logs

# 搜索空证据
rg -n "empty_evidence|insufficient_info_reasons|used_evidence_refs" resume_query_ai_qa/logs
```

## 日常建议

- 新人和日常排障优先使用 `query_logs`，不要一上来阅读大型 detail JSON。
- 先看 `diagnosis`，不要一上来打开大 detail JSON。
- 失败优先定位层级：plan、execution、answer。
- 发生 repair 时，一定检查 repair 后下一次 validator 结果。
- 证据为空不等于失败；只有工具异常、候选人不存在、参数绑定失败才按失败处理。
