# Session Context Node Helpers

## 职责

`session_context` 是 graph 终端节点使用的上下文辅助包。它为 `final`、
`clarification`、`failed` 等终端输出准备展示安全的会话上下文，例如候选人选项和
上下文缺失说明。

它不是业务问答节点，不规划、不执行工具、不生成最终答案。

## 输入

| 输入 | 来源 | 用途 |
| --- | --- | --- |
| `session_state` | API/graph | 读取上一轮可用上下文。 |
| `question` | user/API | 判断是否需要候选人消歧提示。 |
| `trace` | graph state | 记录终端上下文元数据。 |
| 只读 public data access | `core.data_access` | 生成展示安全的候选人列表。 |

## 输出

| 输出 | 写回字段 | 下游 |
| --- | --- | --- |
| 候选人选项 | terminal response metadata | API / 前端 |
| 上下文缺失说明 | `diagnosis.failed_reason` / terminal metadata | API / 前端 |
| 终端 trace 摘要 | `decision_steps[]` | API diagnosis |

## 主流程

```text
clarification -> session_context helpers -> END
final         -> session_context helpers -> END
failed        -> session_context helpers -> END
```

无上下文代词问题，例如“他有哪些金融经历？”，当前契约是
`needs_clarification + required_context_missing`，并进入 clarification。前端应直接展示失败原因，
Debug 中继续提供 trace 定位。

## 失败 / Repair / Fallback

| 场景 | 行为 | 字段 |
| --- | --- | --- |
| 会话里没有可用候选人上下文 | 进入上下文澄清。 | `clarification_reason=required_context_missing` |
| 候选人选项读取为空 | 只返回空选项，不补造候选人。 | `warnings[]` 或 terminal metadata |
| public data access 异常 | 记录终端辅助失败，不影响已生成的最终答案事实。 | `tool_failures[]` 或 node `errors[]` |

该包不负责 repair；repair 只发生在 planner/execution/answer 对应节点。

## Trace 字段

| 字段 | 含义 |
| --- | --- |
| `decision_steps[].summary` | 终端节点展示摘要。 |
| `diagnosis.failed_node` | 如果上下文不可恢复，标记失败节点。 |
| `diagnosis.failed_reason` | 例如 `required_context_missing`。 |
| `trace_lookup` | Debug 下定位 detail JSON。 |
| `warnings[]` | 展示辅助为空或降级时的非阻断提示。 |

## 边界：能做 / 不能做

| 能做 | 不能做 |
| --- | --- |
| 为终端输出准备展示安全元数据。 | 直接 import `resume_query_tools` 调业务工具。 |
| 读取 narrow `core.data_access` public 接口。 | 改写 graph state 中的事实结果。 |
| 标记上下文缺失原因。 | 生成业务答案或修复计划。 |
| 保持前端可解释。 | 把缺上下文问题伪装成成功。 |

## 扩展方式

1. 新增 terminal metadata 时先确认前端是否需要展示。
2. 所有新增失败原因必须同步 API README 和 `QUERY_AI_LOGS.md` 字段词典。
3. 保持 helper 只读、窄接口，不让终端节点反向依赖工具层。
4. 不要在这里补业务 fallback；主链路 fallback 应留在对应 validator/repair 节点。

## 验收 benchmark

```bash
.venv/bin/python -m compileall -q resume_query_ai_qa
.venv/bin/python resume_query_ai_qa/benchmarks/run_runtime_contract_benchmark.py
.venv/bin/python resume_query_ai_qa/benchmarks/run_plan_contract_benchmark.py
```
