# Router Flow

这份文档只讲代码阅读线。

更高层总结看 `README.md`；YAML 字段归属看 `YAML_USAGE.md`。

## 阅读顺序

```text
1. ROUTER_FLOW.md
2. node.py
3. llm.py
4. rules.py
5. signals.py
6. guard.py
7. conditions.py
8. finalizer.py
9. rule_types.py
```

## 5 阶段 Pipeline

```text
preprocess_router_question
-> build_router_draft
-> apply_router_guards
-> complete_router_conditions
-> finalize_router_output
```

| 阶段 | 函数 | 输入 | 输出 | 为什么这么做 |
|---|---|---|---|---|
| 1 | `preprocess_router_question` | raw question | cleaned question | 先统一标点、去掉开头 filler terms，让后续规则匹配更稳定 |
| 2 | `build_router_draft` | cleaned question + config | RouterOutput draft | 先用 LLM 或 rule fallback 给出完整草稿 |
| 3 | `apply_router_guards` | draft | guarded draft | 用硬规则纠偏安全、排序、对比、证据、复合、上下文 |
| 4 | `complete_router_conditions` | guarded draft + question | completed draft | 防止 draft 漏掉 domain/skill/major/scope/candidate_name |
| 5 | `finalize_router_output` | completed draft | final RouterOutput | 统一收口 shape、YAML contract、derived flags |

## node.py

`node.py` 只串流程，不写业务规则。

```text
route_question
route_question_llm
run_router_pipeline
build_router_draft
safe_finalize_router_output
```

核心主链：

```python
cleaned_question = preprocess_router_question(question, config)
draft = build_router_draft(cleaned_question, config, use_llm=use_llm)
guarded = apply_router_guards(draft, cleaned_question, config)
completed = complete_router_conditions(guarded, cleaned_question, config)
return safe_finalize_router_output(completed, cleaned_question, config)
```

含义：

- `route_question()`：纯规则入口。
- `route_question_llm()`：LLM 优先入口，失败时回退规则。
- `build_router_draft()`：只决定草稿来自 LLM 还是 rules。
- `safe_finalize_router_output()`：finalizer 异常时安全降级为 `out_of_scope`。

## llm.py

LLM 路径负责生成和校验 RouterOutput draft。

```text
build_llm_router_draft
run_llm_router
coerce_router_payload
normalize_router_payload_shape
validate_router_payload_schema
validate_scenario_contract
build_llm_fallback_flag
extract_valid_intent_tokens
```

流程：

```text
调用 LLM
-> 转成 dict
-> 修 payload 形状
-> 校验 RouterOutput schema
-> 校验 intent/scenario 合法性
-> 失败则 rule fallback
```

为什么这么做：

- LLM 可以给完整语义草稿。
- 但 LLM 输出不稳定，所以必须 schema 校验。
- `normalized_conditions` 和 `allowed_tool_names` 不信任 LLM，后续阶段重算。

## rules.py + signals.py

Rule fallback 是 deterministic draft 路径。

```text
build_rule_router_draft
-> extract_conditions
-> detect_router_signals
-> infer_rule_sub_intents
-> RULE_INTENT_HANDLERS
-> build_rule_router_output
```

`signals.py` 是侦察层，只回答“文本里有什么信号”：

```text
pair_compare
candidate_reference
context_policy
discovery
project_listing
evidence_locator
single_candidate_fit
interview_question
sensitive_interview
```

`rules.py` 是决策层，把信号变成 draft intent：

```text
count terms -> candidate_count
list terms -> candidate_list
profile terms -> candidate_profile_intro
evidence terms -> evidence_question
pair compare -> candidate_compare_pair
ranking terms -> candidate_ranking
condition fallback -> candidate_filter
```

为什么这么做：

- LLM 不可用时仍能工作。
- 规则 draft 可解释，适合 benchmark 和回归测试。
- signals 和 rules 分开，避免“检测文本”和“决定 intent”混在一起。

## guard.py

Guard 是硬规则纠偏层，不从零生成 RouterOutput。

```text
apply_router_guards
-> apply_safety_guard
-> apply_intent_override_guards
   -> apply_ranking_guard
   -> apply_pair_compare_guard
   -> apply_evidence_guard
-> apply_compound_guard
-> apply_context_guard
-> apply_intent_convergence_guard
```

每类 guard 的意义：

| guard | 作用 |
|---|---|
| safety | 敏感面试问题强制 `out_of_scope` |
| ranking | 明显多人排序强制 `candidate_ranking` |
| pair compare | 明确两人对比强制 `candidate_compare_pair` |
| evidence | 命中“依据/证据/为什么”时补 `evidence_question` |
| compound | 根据 `compound_rules` 补 count/list/ranking/evidence 子任务 |
| context | 解析“第一名/这些人/这两个人/刚才那个人” |
| convergence | 把 `follow_up` 或单人适配问题收敛成具体 intent |

`compound_rules` 映射：

```text
count_terms -> candidate_count
list_terms -> candidate_list
ranking_terms -> candidate_ranking
evidence_terms -> evidence_question
```

为什么这么做：

- draft 可能来自 LLM，不能完全信任。
- 某些场景错了会让后续工具执行偏掉，必须用确定性规则兜住。
- guard 只纠偏明显硬边界，最终权威字段仍交给 finalizer。

## conditions.py

conditions 负责两个阶段：

```text
preprocess_router_question
complete_router_conditions
normalize_router_punctuation
```

`preprocess_router_question()`：

```text
读取 router_rules.preprocess
统一标点
去掉开头 filler terms
压缩空格
```

`complete_router_conditions()`：

```text
保留 draft conditions
重新 extract_conditions(question)
候选人名字走 candidate_reference_conditions
合并去重
保持 normalized_conditions=[]
```

为什么这么做：

- LLM/rule draft 都可能漏条件。
- raw `QueryCondition` 必须尽量补齐。
- `NormalizedCondition` 属于后续 `condition_normalizer`，router 不抢职责。

## finalizer.py

Finalizer 是 RouterOutput 权威收口层。

```text
finalize_router_output
-> finalize_router_shape
-> finalize_router_contract
-> finalize_router_derived_flags
```

三段含义：

| 分组 | 负责字段 | 意义 |
|---|---|---|
| Shape | `intent`、`is_compound`、`sub_intents`、`evidence`、`conditions` | 保证 RouterOutput 内部结构自洽 |
| Contract | `scenario_decisions`、`allowed_tool_names` | 保证 scenario/tool 符合 YAML 合同 |
| Derived Flags | `requires_jd`、`requires_evidence`、`risk_flags` | 统一重算派生字段 |

为什么这么做：

- LLM/rule/guard 都可能改字段。
- finalizer 防止字段之间互相矛盾。
- 后续节点只应该信 finalizer 后的 RouterOutput。

## 示例走读

问题：

```text
金融候选人有几个，谁最强，依据是什么？
```

1. preprocess：

```text
统一标点，清理 filler terms。
```

2. draft：

```text
金融 -> condition domain=金融
几个 -> candidate_count
谁最强 -> candidate_ranking
依据 -> evidence_question
```

3. guard：

```text
compound_rules 确保 count/ranking/evidence 三个子任务都在。
```

4. condition completion：

```text
补齐/去重 conditions，保持 normalized_conditions=[]。
```

5. finalizer：

```json
{
  "intent": "compound",
  "is_compound": true,
  "sub_intent_candidates": [
    "candidate_count",
    "evidence_question",
    "candidate_ranking"
  ],
  "scenario_decisions": {
    "candidate_count": "hard_filter",
    "evidence_question": "evidence_lookup",
    "candidate_ranking": "compare_rank"
  },
  "conditions": [
    {"type": "domain", "raw_value": "金融"}
  ],
  "requires_jd": true,
  "requires_evidence": true,
  "allowed_tool_names": []
}
```

`allowed_tool_names=[]` 是因为 compound 会由后续 compiler 按每个 sub-intent 分别选工具。
