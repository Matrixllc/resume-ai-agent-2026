# Answer Rewrite Node

## 职责

`answer_rewrite` 是 `answer_validator` 之后的答案修复节点。它基于上一版答案、
`ValidationIssue`、`QueryPlan` 和本轮 `ToolResult` 修复表达，使答案重新满足
grounding、隐私、布局和空证据契约。

它不重新调用工具、不补造事实、不改变业务结论。

## 输入

| 输入 | 来源 | 用途 |
| --- | --- | --- |
| `aggregated_answer` | aggregator | 被修复的上一版答案。 |
| `answer_validation_errors[]` | answer_validator | 决定修复策略。 |
| `compiled_plan` | plan_compiler | 保持答案仍覆盖原计划。 |
| `tool_results` | executor | 规则重建答案的事实来源。 |
| `trace` | graph state | 记录 repair/fallback 原因。 |

## 输出

| 输出 | 写回字段 | 下游 |
| --- | --- | --- |
| 修复后的答案 | `aggregated_answer` | `answer_validator` 复检 |
| 修复动作 | `repair_action` | API diagnosis / detail JSON |
| 修复原因 | `repair_reason` | API diagnosis / detail JSON |
| fallback 原因 | `fallback_reason` | API diagnosis / 前端 Debug |

## 主流程

```text
answer_validator
  -> answer_rewrite
     -> policy.py
     -> rule_repair 或 llm_rewrite
  -> answer_validator
```

warning-only 不进入 rewrite；真正需要 rewrite 的错误必须由 `answer_validator`
明确给出。

## 失败 / Repair / Fallback

| 场景 | 行为 | 字段 |
| --- | --- | --- |
| count/name/ranking/evidence_id 错误 | 丢弃不稳定文本，用规则答案重建。 | `repair_action=rule_repair` |
| privacy 错误 | 优先规则重建，避免继续传播泄露内容。 | `repair_reason=privacy` |
| evidence coverage 不足 | 基于工具结果补充证据不足或空证据说明。 | `repair_reason=evidence_coverage` |
| layout 缺失 | 按 layout contract 规则重建。 | `repair_action=rule_repair` |
| 未覆盖的可修复表达问题 | 可走 LLM rewrite，再由 validator 复检。 | `repair_action=llm_rewrite` |
| 修复后仍不合格 | 路由到 rule fallback 或失败。 | `route_events[]`、`answer_validation_errors[]` |

空证据场景只修表达，不触发检索回退：如果工具正常返回 0 条，rewrite 应补“未查到证据”而不是重新搜索。

## Trace 字段

| 字段 | 含义 |
| --- | --- |
| `repair_action` | 本节点采取的修复动作，例如 `rule_repair`、`llm_rewrite`。 |
| `repair_reason` | 为什么修复，例如 `privacy`、`evidence_coverage`。 |
| `fallback_reason` | 修复无法继续时的 fallback 原因。 |
| `error_category` | 触发修复的 validator 分类。 |
| `route_events[]` | 从 validator 到 rewrite、从 rewrite 回 validator 的路由记录。 |
| `aggregator_io_tail[]` | 如使用 LLM rewrite，Debug detail 保留 prompt/response 尾部。 |

## 边界：能做 / 不能做

| 能做 | 不能做 |
| --- | --- |
| 修复不合格答案表达。 | 重新执行 evidence 工具。 |
| 基于工具结果规则重建答案。 | 新增工具结果没有的事实。 |
| 清除隐私/漂移/错误引用。 | 修改 `compiled_plan` 或 scenario。 |
| 记录 repair 可观测字段。 | 将不可修复问题伪装成成功。 |

## 扩展方式

1. 新增 answer validator category 后，同步在 `policy.py` 定义 repair 策略。
2. 优先使用规则重建；只有纯表达问题才允许 LLM rewrite。
3. 新增 repair/fallback 原因时同步更新 `QUERY_AI_LOGS.md`、API README 和前端诊断文案。
4. 扩展后必须确保修复答案再次经过 `answer_validator`。

## 验收 benchmark

```bash
.venv/bin/python -m compileall -q resume_query_ai_qa
.venv/bin/python resume_query_ai_qa/benchmarks/run_runtime_contract_benchmark.py
.venv/bin/python resume_query_ai_qa/benchmarks/run_runtime_contract_benchmark.py
```
