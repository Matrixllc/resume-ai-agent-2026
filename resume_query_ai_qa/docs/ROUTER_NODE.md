# Router Node

router 是 `ai-query` 的协议入口。它只回答一个问题：用户这句话应该被系统理解成什么 `RouterOutput`。

它不做这些事：

- 不决定 template/generic。
- 不生成 tool calls。
- 不查 SQLite/Chroma。
- 不回答用户问题。

它会产出 `scenario_decisions`。LLM router 优先给出每个 intent 的 scenario；
LLM 不可用、输出缺字段或 scenario 不符合 YAML 合同时，router 会整包回到
rule fallback。finalizer 会保留合法 LLM scenario，并用 rule fallback 补齐缺失
或被 guard 改动后的场景。

## 内部流程

```text
query_preprocess
-> llm_or_rule_classify
-> payload_normalize
-> schema_validate
-> rule_guard
-> condition_completion
-> finalizer
-> RouterOutput
```

| 步骤 | 做什么 | 联动配置 |
|---|---|---|
| `query_preprocess` | 清理空白、统一标点、去掉轻量口头前缀 | `configs/router_rules.yaml.preprocess` |
| `llm_or_rule_classify` | LLM 产 draft，包含 intent、conditions 和 scenario_decisions；LLM 不可用时 rule fallback | `core/llm/prompts.py`、`intents.yaml`、`scenarios.yaml`、`router_rules.yaml.intent_rules` |
| `payload_normalize` | 修补 LLM JSON 形状，补默认字段 | `schemas.py::RouterOutput`、`intents.yaml` |
| `schema_validate` | Pydantic 校验 RouterOutput，并校验每个 intent 都有合法 scenario | `schemas.py::RouterOutput`、`scenarios.yaml` |
| `rule_guard` | 强制覆盖高风险误判 | `router_rules.yaml` |
| `condition_completion` | 补齐原始 `conditions` | `shared_taxonomy/domains/*.yaml`、候选人 mention 规则 |
| `finalizer` | 保留合法 LLM scenario；对缺失/非法场景使用 rule fallback，并重算权威派生字段 | `intents.yaml`、`scenarios.yaml`、`tool_policy.yaml` |

## 文件边界

| 文件 | 职责 |
|---|---|
| `node.py` | 只串主流程：preprocess、draft、guard、condition completion、finalizer |
| `rules.py` | 只做 rule fallback：`detect_router_signals -> infer_rule_sub_intents -> build_rule_router_output` |
| `guard.py` | 每次执行硬边界 override：safety、context、pair/ranking/evidence、compound、convergence |
| `finalizer.py` | 按字段顺序重算 RouterOutput 权威字段 |

`rules.py` 不再维护大段硬编码词表。触发词、上下文词、敏感词、intent reason、risk flag 白名单都在 `configs/router_rules.yaml`；Python 只保留候选人识别、组合判断和 contract 构造。

## Rule Guard

`rule_guard` 每次都执行。LLM 可以判断主语义，但硬边界必须确定性兜住。

| Guard | 触发例子 | 输出 |
|---|---|---|
| `context_guard` | `第一名有哪些项目？` | `context_policy.context_ref_type=ranking_top` |
| `safety_guard` | `Python 是什么？` / `针对孟连星问年龄` | `out_of_scope`，`allowed_tool_names=[]` |
| `intent_override_guard` | `孟连星和孔德程谁更好？` / `体现在哪里？` | `candidate_compare_pair` 或补 evidence 子任务 |
| `compound_guard` | `金融候选人有几个，谁最强，依据是什么？` | `candidate_count + candidate_ranking + evidence_question` |

判断 `Python 是什么？` 的关键不是出现 `Python`，而是没有简历检索动作。`谁会 Python？` 有“谁/会”，所以仍是简历筛选。

## Condition Completion

`condition_completion` 是条件补全，不是条件标准化。

它会合并：

```text
LLM conditions + rule extracted conditions
```

可以补：

- `domain`：金融、能源、运营等。
- `skill`：Python、SQL 等。
- `concept`：推荐系统、风控系统等。
- `major`：`XX专业`。
- `scope`：项目经验、工作经历、相关背景。
- `candidate_name`：孟连星、孔德程等候选人 mention。

它不会生成：

- `normalized_conditions`
- tool arguments

`normalized_conditions` 仍由 `condition_normalizer` node 生成。

## Finalizer 字段权威

`scenario_decisions`、`requires_jd`、`requires_evidence` 可以由 LLM 给初值，
但最终以 schema validate、rule guard 和 finalizer 收口后的结果为准。

| 字段 | Finalizer 规则 |
|---|---|
| `scenario_decisions` | 保留符合 `scenarios.yaml` 的 LLM 场景；缺失、非法或 rule guard 改动后的场景用 rule fallback 补齐 |
| `requires_jd` | `candidate_ranking/jd_scoring` 或 compound 子任务包含它们时为 true |
| `requires_evidence` | profile/evidence/compare/ranking/interview 或证据触发词命中时为 true |
| `allowed_tool_names` | 非 compound/out_of_scope 时从 `tool_policy.yaml` 读取；compound/out_of_scope 为 `[]` |
| `risk_flags` | 只保留系统白名单内审计标记 |

## 失败处理

| 失败点 | 处理 |
|---|---|
| LLM timeout/API error/非 JSON | 回到 rule fallback，追加 `llm_router_fallback:<reason>` |
| schema validate 失败，或 LLM 漏给/错给 scenario | 回到 rule fallback，追加 `router_schema_validation_failed:<reason>` |
| rule guard 局部异常 | 保留当前 draft，追加 `router_rule_guard_failed:<reason>` |
| condition completion 异常 | 保留已有 conditions，追加 `condition_completion_failed:<reason>` |
| finalizer 异常 | 安全降级 `out_of_scope` |

## 典型输出

`谁会 Python？`

```json
{
  "intent": "candidate_filter",
  "sub_intent_candidates": ["candidate_filter"],
  "scenario_decisions": {
    "candidate_filter": {
      "scenario": "hard_filter",
      "source": "llm",
      "reason": "用户提出明确技能准入条件"
    }
  },
  "conditions": [{"type": "skill", "raw_value": "Python"}],
  "normalized_conditions": [],
  "requires_jd": false,
  "requires_evidence": false
}
```

`金融候选人有几个，谁最强，依据是什么？`

```json
{
  "intent": "compound",
  "sub_intent_candidates": ["candidate_count", "candidate_ranking", "evidence_question"],
  "requires_jd": true,
  "requires_evidence": true,
  "allowed_tool_names": []
}
```
