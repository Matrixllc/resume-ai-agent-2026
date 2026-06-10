# Router Node

## 职责

`router` 是 Query-AI 协议入口。它把用户问题收敛成 `RouterOutput`，包括 intent、
scenario decisions、raw conditions、compound 子意图、上下文引用策略、risk flags
和允许工具名初稿。

## 输入

| 输入 | 来源 | 用途 |
|---|---|---|
| `question` | 用户请求 | 语义分类、条件抽取、out-of-scope 判断。 |
| `session_context` | 上轮 final 写回 | 识别“他/这些人/第一名/这两个人”。 |
| router YAML | `configs/router_rules.yaml` | guard、open recall 词、上下文词、敏感问题规则。 |
| intents YAML | `configs/intents.yaml` | 合法 intent 和默认 evidence/JD 要求。 |

## 输出

| 输出 | 用途 |
|---|---|
| `RouterOutput.intent` | 下游主 intent。 |
| `sub_intent_candidates` | compound 问题拆分。 |
| `scenario_decisions` | 每个 intent 的 canonical 执行协议，供 policy/compiler/validator 消费。 |
| `conditions` | 原始条件，交给 `condition_normalizer` 标准化。 |
| `context_policy` | 标记是否需要 session context。 |
| `requires_evidence` / `requires_jd` | 下游 policy 和 compiler 的初始信号。 |
| `risk_flags` | LLM fallback、schema 修补、敏感边界等诊断信息。 |

## 主流程

```text
preprocess_router_question
-> build_router_draft
-> apply_router_guards
-> complete_router_conditions
-> finalize_router_output
-> RouterOutput
```

rule-only 路径跳过 LLM，但仍执行 guard、condition completion 和 finalizer。

更详细的阅读顺序见同目录的 `ROUTER_FLOW.md`。

## 失败 / Fallback

| 场景 | 行为 | Trace 字段 |
|---|---|---|
| LLM 不可用或返回非法 payload | rule draft fallback | `fallback_reason`、`risk_flags` |
| schema validate 失败 | rule draft fallback | `router_schema_validation_failed:*` |
| finalizer 异常 | safe out_of_scope | `router_finalizer_failed:*` |
| 非简历问题 | `intent=out_of_scope` | tools 为空，后续不查简历工具 |

## Trace 字段

重点看：

- `decision_steps[].node=router`
- `summary=intent=...`
- `fallback_reason`
- `risk_flags`
- `conditions`
- `scenario_decisions`
- `context_policy`

## 边界：能做 / 不能做

能做：

- 判断 intent、scenario、compound、上下文引用、out-of-scope。
- 生成原始 `conditions`。
- 标记风险和 fallback。

不能做：

- 不生成 `ToolCallSpec`。
- 不拼工具参数。
- 不调用 tools。
- 不生成最终答案。

## 扩展方式

- 新意图：更新 `intents.yaml`、router rules 和 router benchmark。
- 新开放召回语气：更新 `router_rules.yaml` 的 `open_recall_terms`。
- 新 scenario：更新 router/finalizer 规则、`scenarios.yaml` 和 policy benchmark。
- 新上下文指代：更新 context guard 和 router context benchmark。
- 新敏感问题边界：更新 guard 和 bad case benchmark。

## 验收 benchmark

```bash
.venv/bin/python resume_query_ai_qa/benchmarks/run_policy_contract_benchmark.py
.venv/bin/python resume_query_ai_qa/benchmarks/run_policy_contract_benchmark.py
.venv/bin/python resume_query_ai_qa/benchmarks/run_runtime_contract_benchmark.py
```
