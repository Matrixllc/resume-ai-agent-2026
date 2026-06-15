# Clarification Node

`clarification` 是主链里的澄清出口。它只把“可以让用户补充的信息”转换成用户可回答的问题，
不查库、不猜测、不修 plan。

## 架构位置

```text
plan_validator / execution_validator / answer_validator
-> graph route
-> clarification
-> final response asking user for missing information
```

它不是正常成功路径的一部分。只有 validator 或 route 判断当前轮缺少必要上下文，并且这个缺口适合让用户回答时，才会进入这里。

## 节点目标

把结构化错误转换成可读澄清问题：

```text
ValidationIssue / route reason
-> clarification question
-> clarification options
```

典型场景：

- 双人比较缺少明确的两位候选人。
- 追问里出现“他/她/第一名/这些人”，但 session context 不能可靠解析。
- 工具或答案层发现当前问题需要用户补充范围，而不能安全 fallback。

## 输入

主要来自 graph state：

| 输入 | 来源 | 用途 |
| --- | --- | --- |
| `question` | 用户原始问题 | 生成澄清问题的上下文。 |
| `validation_result` / errors | plan/execution/answer validator | 判断缺少什么信息。 |
| `router_output.context_policy` | router | 辅助判断是否是上下文引用缺失。 |
| `session_context` | 上一轮 final 写回 | 提供可选候选人、候选池、排名等上下文。 |

## 输出

写回 graph state 中的澄清信息，供 API/前端展示：

| 输出 | 含义 |
| --- | --- |
| `clarification_question` | 给用户看的问题。 |
| `clarification_options` | 可选项，例如候选人名字或候选范围。 |
| `diagnosis` | trace/debug 中解释为什么需要澄清。 |

## 它做什么

- 把缺失上下文变成用户可回答的问题。
- 保留 validator 给出的失败原因。
- 尽量给出有限选项，降低用户再次输入的成本。
- 结束当前轮，不继续 executor / aggregator。

## 它不做什么

- 不调用 tools。
- 不读取 SQLite/Chroma。
- 不修改 `QueryPlan`。
- 不生成业务答案。
- 不根据模糊代词强行猜候选人。
- 不把不可恢复错误伪装成澄清。

## 示例

用户问：

```text
这两个人谁更强？
```

如果 session context 没有上一轮明确的两位候选人：

```text
plan_validator / route
-> 发现 compare 需要 two_candidates
-> clarification
-> "你想比较哪两位候选人？"
-> options: ["张伟", "李静", "赵敏", ...]
```

这里不能直接猜“这两个人”是谁，因为猜错会导致后续工具链、排名和证据全部建立在错误候选人上。

## 和其他节点的边界

| 节点 | 边界 |
| --- | --- |
| `router` | 识别上下文引用意图，但不负责向用户发问。 |
| `plan_validator` | 判断计划是否缺少必要条件。 |
| `execution_validator` | 判断工具结果是否缺少必要事实。 |
| `answer_validator` | 判断答案是否能安全放行。 |
| `clarification` | 只把可澄清问题表达给用户。 |

## 验收

```bash
.venv/bin/python -m compileall -q resume_query_ai_qa
.venv/bin/python resume_query_ai_qa/benchmarks/run_policy_contract_benchmark.py
.venv/bin/python resume_query_ai_qa/benchmarks/run_runtime_contract_benchmark.py
```
