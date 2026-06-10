# Debug And Fallback

这份文档说明 Query-AI 遇到问题时如何 repair/fallback，以及前后端如何通过
`trace_id` 溯源。

## Debug 数据从哪里来

每个 graph node 都会写入 `trace.decision_log`，后端日志落在：

```text
resume_query_ai_qa/logs/qa_runs.jsonl
resume_query_ai_qa/logs/<timestamp>_<trace_id>.json
```

`/qa/ask` 默认返回最小诊断：

| 字段 | 含义 |
| --- | --- |
| `trace.diagnosis.headline` | 当前问题的一句话诊断。 |
| `trace.diagnosis.status` | `ok`、`failed` 或 `needs_clarification`。 |
| `trace.diagnosis.failed_node` | 失败节点，成功时为空。 |
| `trace.diagnosis.failed_reason` | 失败原因。 |
| `trace.diagnosis.warnings` | 非阻断 warning，例如 `empty_evidence`。 |

`debug=true` 时额外返回：

| 字段 | 含义 |
| --- | --- |
| `decision_steps[]` | 每个节点的 `status/summary/errors/warnings/fallback_reason/repair_action/repair_reason/error_category/duration_ms`。 |
| `route_events[]` | validator 路由到 repair/fail/clarify/fallback/final 的原因。 |
| `tools[]` / `tool_failures[]` | 工具执行摘要和失败摘要。 |
| `validation_errors` | plan / execution / answer 三层错误。 |
| `router_scenarios[]` | 每个 intent 的 scenario、来源、原因和证据；用于证明 LLM scenario 是否被保留或 rule fallback 是否接管。 |
| `semantic_plan` / `compiled_plan` | 语义计划和最终工具调用。 |
| `execution_decision` / `compiler_decision` | 执行和编译决策。 |
| `trace_lookup` | detail JSON 定位。 |

API 只汇总已有 trace，不重新判断业务事实。

## Fallback / Repair 类型

| 问题 | 发现节点 | 处理方式 | Debug 看哪里 |
| --- | --- | --- | --- |
| LLM router 失败 | router | rule fallback | `decision_steps[].fallback_reason`、`router_scenarios[].source=rule_fallback` |
| LLM router 漏给或错给 scenario | router schema validate | 整包 rule fallback | `risk_flags`、`router_scenarios[].source=rule_fallback` |
| LLM planner 失败 | planner | rule semantic plan | `planner.engine=rule_fallback` |
| LLM aggregator 失败 | aggregator | rule grounded draft | `aggregator.fallback_reason` |
| 缺少上下文 | plan_validator | fail 或少数 clarify | `validation_errors.plan`、`diagnosis.failed_reason` |
| 工具不允许 | plan_validator | plan repair / fail | `validation_errors.plan`、`route_events[]` |
| 工具参数引用失败 | executor | failed ToolResult | `tools[].status=failed` |
| 工具结果异常 | execution_validator | execution repair / fail | `validation_errors.execution` |
| 工具正常返回 0 条证据 | execution_validator / aggregator | answerable，记录 warning | `empty_evidence`、`diagnosis.warnings` |
| 答案越界 | answer_validator | answer rewrite / rule fallback | `validation_errors.answer` |
| 非简历问题 | router | out_of_scope no tools | `intent`、empty tools |

## 前端怎么查

1. 先看问答状态卡的 `diagnosis.headline`。
2. 失败时看 `failed_node` 和 `failed_reason`。
3. 开启 Debug 后重新提问，查看“诊断摘要”。
4. 看 `route_events[]`，确认是 repair、fallback、fail 还是 final。
5. 看节点时间线：每个节点的 `status + summary`。
6. 看 validation errors，判断是 plan、execution 还是 answer 层。
7. 最后再看 Semantic Plan、Compiled Plan、Tools 和原始证据面板。

## 后端怎么查

```bash
# 最近运行摘要
tail -n 20 resume_query_ai_qa/logs/qa_runs.jsonl

# 根据前端 Trace ID 找 detail
ls resume_query_ai_qa/logs/*<trace_id>*.json

# 格式化查看 detail
python -m json.tool resume_query_ai_qa/logs/<timestamp>_<trace_id>.json | less

# 搜索 fallback / repair / route
rg -n "fallback_reason|repair_action|repair_reason|route_events" resume_query_ai_qa/logs

# 搜索 validator error
rg -n "plan_validation_errors|execution_validation_errors|answer_validation_errors" resume_query_ai_qa/logs

# 搜索工具失败
rg -n "\"status\": \"failed\"|tool_failures|\"ok\": false|\"error\"" resume_query_ai_qa/logs

# 搜索空证据
rg -n "empty_evidence|insufficient_info_reasons|used_evidence_refs" resume_query_ai_qa/logs
```

## 典型 Bad Case

| 问题 | 预期 |
| --- | --- |
| `他有哪些金融经历？` 且无上下文 | `needs_clarification + required_context_missing` |
| `这些人里谁更好？` 且无候选池 | `failed`，缺 candidate_pool |
| `今天天气怎么样？` | `out_of_scope`，tools 为空 |
| `Python 是什么？` | `out_of_scope`，不能误判成技能筛选 |
| `可能的金融领域候选人` | `open_recall`，可用 `hybrid_search_candidates` |
| `金融领域候选人有哪些？` | `hard_filter`，必须用 `filter_candidates(domains_any=[...])` |
| `孙可欣 有能源相关的经历么` 且 evidence 为空 | `ok`，warning=`empty_evidence`，答案说明未查到证据 |
| aggregator LLM 超时 | rule grounded draft fallback |

## 排查顺序

1. `diagnosis.headline`
2. `diagnosis.failed_node` / `failed_reason`
3. `route_events[]`
4. `validation_errors.plan/execution/answer`
5. `decision_steps[]`
6. `tools[]`
7. `decision_log[].debug`（仅 Debug 深度模式）

## 常见误判

- 业务结果 ok 但 benchmark 失败：可能是严格要求无 LLM fallback。
- 前端看不到完整 trace：通常是没开 Debug；默认只返回最小诊断。
- 工具没调用不一定是 bug：out_of_scope 本来就不查简历工具。
- 证据为空不等于失败：正常 0 证据是 `ok + empty_evidence warning`。
- generic 不代表不稳定：它仍然要经过 compiler、validator、executor 和 answer validator。
