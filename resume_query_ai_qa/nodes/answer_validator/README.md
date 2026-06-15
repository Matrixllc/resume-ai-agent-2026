# Answer Validator Node

## 一句话

`answer_validator` 是最终答案出口前的只读闸门：

```text
aggregator / answer_rewrite
-> answer_validator
-> final / answer_rewrite / rule_answer_fallback / failed
```

它检查 `AggregatedAnswer` 是否符合工具事实、结构化 claims、证据引用、隐私、布局和证据覆盖合同。

## 架构位置

```text
executor
-> execution_validator
-> aggregator
-> answer_validator
-> final
```

如果答案不合格，graph 会根据 `ValidationResult` 路由到 `answer_rewrite`、rule fallback 或失败出口。

## 节点目标

`answer_validator` 的目标是判断“这份最终答案能不能交给用户”。

它做：

```text
校验 claims 是否有成功工具支持
校验 count 是否等于 count_candidates
校验 candidate name 是否来自工具结果
校验 ranking 是否等于 rank_candidates
校验 evidence_id 是否真实存在
校验隐私字段是否泄露
校验 answer layout 是否符合 YAML
校验必需 structured claims 是否存在
校验证据覆盖和空证据表达
```

它不做：

```text
不调用工具
不重写答案
不修改 QueryPlan
不重新执行工具
不重新检索数据
不逐句核验 LLM answer 文本里的所有自然语言事实
```

## 输入

| 输入 | 来源 | 用途 |
| --- | --- | --- |
| `answer: AggregatedAnswer` | `aggregator` / `answer_rewrite` | 被校验的最终答案对象。 |
| `tool_results: ToolResult[]` | `executor` | 提供 count、ranking、候选人、证据等事实来源。 |
| `plan: QueryPlan` | `plan_compiler` | 判断本轮是否需要 count/name/ranking/comparison 等结构化 claim。 |
| `config: ResumeQAConfig` | YAML loader | 提供 answer、privacy、layout、evidence policy 等合同。 |

## 输出

| 输出 | 含义 | 下游 |
| --- | --- | --- |
| `ValidationResult.ok` | 是否通过答案校验。 | route |
| `ValidationResult.errors[]` | 阻断性错误 message；非空时通常进入 rewrite/fallback。 | route / diagnosis / debug |
| `ValidationResult.warnings[]` | 非阻断风险 message，例如证据覆盖 warning。 | API diagnosis / debug |
| `ValidationResult.error_details[]` | `ValidationIssue[]`，包含 category/code/message/severity/repairable/details。 | route / diagnosis / debug |
| `ValidationResult.next_node` | validator 建议的下一跳；当前通过为 `final`，失败为 `answer_rewrite`。 | graph route |

当前实现没有单独的 answer validator 决策对象。运行诊断里的 decision/route 信息由
graph trace 根据 `ValidationResult` 和 state 汇总生成。

## 主流程

入口函数是 `validate_answer()`：

```text
validate_answer
-> validate_claim_support
-> validate_answer_count
-> validate_answer_names
-> validate_answer_ranking
-> validate_answer_evidence_refs
-> validate_answer_contact
-> validate_answer_layout
-> validate_required_structured_claims
-> validate_evidence_coverage
-> ValidationResult
```

详细阅读线见 `ANSWER_VALIDATOR_FLOW.md`。

## 关键边界

### claims / evidence refs 来自哪里

当前主链里，LLM 可以生成 `answer.answer` 文本，但 aggregator 会用 grounded 结果收口：

```text
final.answer = LLM answer text 或 grounded fallback answer
final.claims = grounded claims
final.used_evidence_refs = grounded evidence refs
final.warnings = grounded warnings + LLM warnings
```

所以 `answer_validator` 校验的 `claims` / `used_evidence_refs` 通常来自 `ToolResult -> grounded_context`，不是完全相信 LLM 自己写的 claims。

### 它如何检查 LLM 文本

`answer_validator` 会检查部分 `answer.answer` 文本：

```text
count 文本数字
ranking 文本中的候选人顺序
privacy 联系方式和敏感属性
layout 标题和章节顺序
empty evidence 是否说明证据不足
```

但它当前不会逐句抽取 LLM 文本里的全部事实，也不会把每句话都和 `ToolResult` 做自然语言蕴含校验。

## 能保证什么

当前能较稳定保证：

```text
数量不乱
排序不乱
候选人名不乱
evidence_id 不乱
隐私不泄露
布局符合 YAML
必需 structured claims 存在
空证据表达符合 evidence policy
```

当前不能完全保证：

```text
LLM answer.answer 里的每一句自然语言事实都逐句来自 tool_results
```

如果后续要增强这点，建议单独新增 `answer_text_grounding_validator`，专门从 LLM 文本抽取候选人、项目、公司、技能、数量、排序、证据表达，再和 grounded context 对齐。

## 文档阅读顺序

```text
1. README.md
2. ANSWER_VALIDATOR_FLOW.md
3. YAML_USAGE.md
4. answer.py
5. answer_claims.py
6. answer_layout.py
7. answer_privacy.py
8. issues.py
```

## 验收

```bash
rg "Answer Validator|ANSWER_VALIDATOR_FLOW|YAML_USAGE|validate_answer|validate_answer_count|validate_answer_ranking|validate_answer_layout" resume_query_ai_qa/nodes/answer_validator
./.venv/bin/python -m compileall -q resume_query_ai_qa/nodes/answer_validator
./.venv/bin/python resume_query_ai_qa/benchmarks/run_policy_contract_benchmark.py
./.venv/bin/python resume_query_ai_qa/benchmarks/run_plan_contract_benchmark.py
./.venv/bin/python resume_query_ai_qa/benchmarks/run_runtime_contract_benchmark.py
```
