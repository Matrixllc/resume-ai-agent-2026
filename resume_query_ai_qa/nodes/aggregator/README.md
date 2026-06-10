# Aggregator Node

## 职责

`aggregator` 是 grounded answer 生成节点。它把已经执行并通过校验的
`ToolResult` 组织成 `AggregatedAnswer`，负责把事实、证据、空结果说明和展示结构
合成给下游答案校验器。

它不是事实层，不调用工具、不读库、不重新规划，也不能把没有证据的经历写成事实。

## 输入

| 输入 | 来源 | 用途 |
| --- | --- | --- |
| `question` | user/API | 判断回答形态和表达重点。 |
| `semantic_plan` / `compiled_plan` | planner / plan_compiler | 理解本轮意图、scenario 和工具合同。 |
| `tool_results` | executor | 生成 grounded context 的唯一事实来源。 |
| `execution_decision` | execution_validator | 判断工具结果是否可进入回答。 |
| `trace` | graph state | 写入 answer generation 元数据。 |

## 输出

| 输出 | 写回字段 | 下游 |
| --- | --- | --- |
| 聚合答案对象 | `aggregated_answer` | `answer_validator` |
| 引用证据 | `aggregated_answer.used_evidence_refs` | `answer_validator` / API trace |
| 结论 claims | `aggregated_answer.claims` | `answer_validator` |
| 空证据 warning | `aggregated_answer.warnings` / trace details | API diagnosis / 前端 Debug |
| aggregator 元数据 | `decision_log` / detail JSON | 排障与审计 |

## 主流程

```text
execution_validator
  -> aggregator
     -> QueryFrame / TaskType
     -> GroundedContext
     -> RuleDraft
     -> Rule Renderer
     -> LLM Fill（可选）
     -> Grounding Merge
  -> answer_validator
```

真实实现的 source of truth 在 `resume_query_ai_qa/core/answer_generation/`。
`nodes/aggregator/` 只保留 graph 可调用入口和历史 import compatibility wrapper。

## 失败 / Repair / Fallback

| 场景 | 行为 | 字段 |
| --- | --- | --- |
| LLM 不可用 | 使用确定性 rule renderer / fallback。 | `fallback_reason=llm_unavailable` 或同类原因 |
| LLM 事实漂移 | 丢弃漂移输出，回到 grounded rule answer。 | `fallback_reason=fact_drift:*`、`drift_rejection_reason` |
| LLM 违反 YAML 硬布局合同 | 丢弃不合格输出，回到 grounded rule answer。 | `fallback_reason=layout_contract:*` |
| 证据工具正常返回 0 条 | 生成可回答的空证据结论。 | `warnings=["empty_evidence"]` 或同等 warning |
| 工具异常或上游执行失败 | 不自行修复，由上游 validator/repair 处理。 | 上游 `execution_validation_errors` |
| claims/evidence/layout 不合格 | 交给 `answer_validator` 判断。 | 下游 `answer_validation_errors` |

空证据是业务结论，不是系统失败：答案应写“未查到相关经历/没有足够证据证明”，不能猜测为“有相关经历”。

## Trace 字段

| 字段 | 含义 |
| --- | --- |
| `task_type` | 本轮回答形态，例如候选人集合、画像、比较、开放 grounded answer。 |
| `freedom_level` | 答案自由度，决定是否允许 LLM 做表达扩展。 |
| `slots` | 从 plan/question 中抽取的展示目标，不是事实判断。 |
| `task_match_reason` | 为什么选中该 task。 |
| `answer_layout` / `answer_layout_source` | 使用的布局与来源。 |
| `layout_match_reason` | 为什么选中该 layout。 |
| `context_summary` | GroundedContext 的摘要。 |
| `llm_mode` | 本轮是否使用 LLM 填充或只用规则。 |
| `drift_rejection_reason` | LLM 输出被拒绝的原因。 |
| `insufficient_info_reasons` | 信息不足原因，包含正常空证据。 |
| `decision_log[].debug` | Debug 深度模式下保留 prompt、response、完整 claims 和 evidence refs。 |
| `decision_log[].fallback_reason` | LLM 不可用、输出漂移或规则回退的短原因。 |

API `trace.diagnosis` 只汇总这些字段，不重新判断事实。

`required_sections` 表示必须回答的语义内容；只有 `required_title_sections` 中声明的
章节才要求答案原样显示 `titles` 中的可见标题。标题和开头章节规则不得在代码中硬编码。

## 边界：能做 / 不能做

| 能做 | 不能做 |
| --- | --- |
| 把工具结果组织成可读答案。 | 调用 `filter_candidates`、`hybrid_search_candidates` 等工具。 |
| 在证据为空时输出空证据结论。 | 把空证据解释成工具失败。 |
| 使用 YAML 驱动 task/layout。 | 在代码里硬编码“金融/能源/某个人名”。 |
| 对 LLM 输出做 grounding merge。 | 信任 LLM 新增的事实。 |
| 写入可观测 trace meta。 | 改变 graph 路由。 |

## 扩展方式

1. 新增回答形态时，优先改 `configs/aggregator_tasks.yaml` 和
   `configs/answer_layouts.yaml`。
2. 只有当现有 TaskType 无法表达结构时，才扩展
   `core/answer_generation/task.py`。
3. 新字段默认进入 `context_summary` 或节点 `output`；大对象仅进入 `decision_log[].debug`，确保 API 和前端默认可读。
4. 新增 fallback 原因时同步更新 `QUERY_AI_LOGS.md` 和 `nodes/README.md` 字段词典。

## 验收 benchmark

```bash
.venv/bin/python -m compileall -q resume_query_ai_qa
.venv/bin/python resume_query_ai_qa/benchmarks/run_runtime_contract_benchmark.py
.venv/bin/python resume_query_ai_qa/benchmarks/run_plan_contract_benchmark.py
.venv/bin/python resume_query_ai_qa/benchmarks/run_runtime_contract_benchmark.py
```
