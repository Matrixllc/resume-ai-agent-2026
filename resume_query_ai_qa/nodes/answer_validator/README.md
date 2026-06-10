# Answer Validator Node

## 职责

`answer_validator` 是答案出口前的只读闸门。它检查 `aggregated_answer` 是否符合
claims、证据引用、隐私、布局和空证据表达契约。

它只产出 validation decision，不改写答案、不调用工具、不重新规划。

## 输入

| 输入 | 来源 | 用途 |
| --- | --- | --- |
| `aggregated_answer` | aggregator / answer_rewrite | 被校验的答案对象。 |
| `tool_results` | executor | 校验 claims 和 evidence refs 是否来自工具事实。 |
| `compiled_plan` | plan_compiler | 校验答案是否覆盖本轮计划要求。 |
| `execution_decision` | execution_validator | 区分正常空证据和执行失败。 |
| `trace` | graph state | 写入校验错误、warning 和路由事件。 |

## 输出

| 输出 | 写回字段 | 下游 |
| --- | --- | --- |
| 校验通过 | `answer_decision.status=ok` | `final` |
| 可修复问题 | `answer_validation_errors[]` | `answer_rewrite` |
| 不可修复问题 | `answer_validation_errors[]` / `route_events[]` | `failed` 或 rule fallback |
| warning | `answer_decision.warnings[]` | API diagnosis / 前端 Debug |

## 主流程

```text
aggregator
  -> answer_validator
     -> final
     -> answer_rewrite
     -> rule_answer_fallback
     -> failed
```

`answer_validator` 是判断“能否把答案交给用户”的地方，不是生成答案的地方。

## 失败 / Repair / Fallback

| 场景 | 行为 | 字段 |
| --- | --- | --- |
| claims 与工具事实不一致 | 标记 hard issue，进入规则修复或失败。 | `answer_validation_errors[].category=claim` |
| evidence refs 引用不存在 | 标记 evidence issue。 | `answer_validation_errors[].category=evidence_id` |
| 必答字段缺失 | 要求 rewrite 或 rule fallback。 | `answer_validation_errors[].category=required_claim` |
| 隐私字段泄露 | 优先 rule repair，丢弃不合格答案。 | `answer_validation_errors[].category=privacy` |
| 证据正常为空且答案说明不足 | 要求补充空证据表达。 | `answer_validation_errors[].category=evidence_coverage` |
| 证据正常为空且答案已说明 | 放行，保留 warning。 | `warnings=["empty_evidence"]` |

`used_evidence_refs=[]` 允许存在，但必须满足两个条件：工具正常返回空结果；答案明确写出
“未查到/证据不足”，不能输出肯定性事实。

## Trace 字段

| 字段 | 含义 |
| --- | --- |
| `answer_validation_errors[]` | 答案校验错误，包含 category/code/message/repairable。 |
| `warnings[]` | 非阻断风险，例如 `empty_evidence`。 |
| `route_events[]` | 从 answer validator 路由到 rewrite/fallback/fail/final 的原因。 |
| `decision_steps[].status` | 当前节点是 `ok`、`warning`、`repair` 还是 `failed`。 |
| `decision_steps[].summary` | 给前端看的节点摘要。 |
| `diagnosis.validation_errors` | API 汇总后的答案校验错误入口。 |

## 边界：能做 / 不能做

| 能做 | 不能做 |
| --- | --- |
| 校验答案是否 grounded。 | 重写答案文本。 |
| 允许正常 0 证据回答。 | 把空证据强行转成 fallback 检索。 |
| 产出可解释 validation issue。 | 调工具补证据。 |
| 决定是否进入 rewrite/fallback/fail。 | 改变上游 plan 或工具结果。 |

## 扩展方式

1. 新增校验项时必须给出稳定 `category` 和 `code`。
2. 每个阻断错误必须说明是否 `repairable`，供 `answer_rewrite` 策略消费。
3. 新增 warning 时同步更新 API README、`QUERY_AI_LOGS.md` 和前端 Debug 展示文案。
4. 不要在 validator 中写领域词特例；领域差异应来自 plan、tool result 和 layout contract。

## 验收 benchmark

```bash
.venv/bin/python -m compileall -q resume_query_ai_qa
.venv/bin/python resume_query_ai_qa/benchmarks/run_runtime_contract_benchmark.py
.venv/bin/python resume_query_ai_qa/benchmarks/run_runtime_contract_benchmark.py
```
