# Rules Package

`core/rules/` 是跨节点复用的确定性规则层。

一句话：

```text
rules = YAML/config + RouterOutput/session context/tool facts -> deterministic decisions
```

它不调用 LLM，不执行工具，不生成最终答案。

## 它做什么

- 从 query / conditions / taxonomy 提取确定性信号。
- 解析 context reference 和 session context。
- 根据 scenario/tool/template 配置生成 execution decision。
- 生成 rule SemanticPlan。
- 提供 evidence policy、behavior contract、session context 清洗。
- 给 plan compiler / repair 复用 plan building 规则。

## 它不做什么

- 不作为 graph node。
- 不调用 tool registry。
- 不读取用户最终答案。
- 不做 LLM fallback。
- 不写 graph state。

## 文件地图

| 文件 | 职责 | 主要使用方 |
| --- | --- | --- |
| `condition_rules.py` | raw/normalized condition 规则、filter args 支撑 | router、condition_normalizer、plan_building |
| `candidate_mentions.py` | 候选人名字/别名提取 | router、condition_normalizer |
| `context_resolver.py` | `他/这些人/第一名/JD` 等上下文引用解析 | router、plan_building |
| `execution_policy_rules.py` | scenario 决策、workflow 匹配、execution decision | execution_policy |
| `semantic_plan.py` | rule SemanticPlan 生成和 LLM plan normalize | planner |
| `evidence_policy.py` | intent/plan 证据要求 | execution_validator、answer_validator |
| `behavior_contract.py` | 工具合同、artifact、validation action 查询 | validators、repair |
| `session_context.py` | session context 白名单和清洗 | graph final、context resolver |
| `taxonomy.py` | shared_taxonomy 读取和 alias 查询 | condition/rules/tools |
| `plan_building/` | QueryPlan 构建规则子包 | plan_compiler、repair |

## 阅读顺序

1. `condition_rules.py`
2. `candidate_mentions.py`
3. `context_resolver.py`
4. `execution_policy_rules.py`
5. `semantic_plan.py`
6. `plan_building/README.md`
7. `behavior_contract.py`
8. `evidence_policy.py`
9. `session_context.py`
10. `taxonomy.py`

## 边界

`rules` 可以依赖：

```text
core.schemas
core.config
shared_taxonomy
read-only data access when needed
```

`rules` 不应该依赖：

```text
graph
nodes
tools
LLM provider
```

## 排查地图

| 问题 | 看哪里 |
| --- | --- |
| condition/filter args 错 | `condition_rules.py` |
| 候选人名误识别 | `candidate_mentions.py` |
| “第一名/这些人/他”解析错 | `context_resolver.py` |
| workflow/template 匹配错 | `execution_policy_rules.py` |
| SemanticPlan 步骤错 | `semantic_plan.py` |
| requires evidence/JD 判断错 | `evidence_policy.py`、`behavior_contract.py` |
