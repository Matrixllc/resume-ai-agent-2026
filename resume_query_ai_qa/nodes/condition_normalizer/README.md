# Condition Normalizer Node

Condition Normalizer 把 router 输出的 raw `conditions` 收敛成下游稳定消费的
`normalized_conditions`。

它是 router 之后的条件权威收口层：router 负责发现原始条件，本节点负责把条件
标准化成可检索、可过滤、可验证的结构。

## 架构位置

```text
user question
-> router
-> condition_normalizer
-> execution_policy
-> planner / plan_compiler
-> executor
-> aggregator
```

## 节点目标

```text
RouterOutput.conditions
-> RouterOutput.normalized_conditions
```

它让后续节点不用猜：

```text
金融 / finance / 金融风控 到底是不是同一个领域？
Python 是 skill 还是 keyword？
第一名 是真实候选人名还是上下文引用？
适合做金融风控 里的“金融风控”是筛选条件还是偏好目标？
```

## 输入 / 输出

| 输入 | 来源 | 用途 |
|---|---|---|
| `RouterOutput` | router | 读取 intent、conditions、context_policy |
| `question` | 用户请求 | conditions 缺失时 fallback 抽取；标记 preference target |
| `condition_rules.yaml` | 公共条件规则 | major/scope 抽取、preference target、匹配约束 |
| `shared_taxonomy/` | 共享分类体系 | domain/skill/concept 标准化 |
| candidate names | data_access | 判断 candidate_name 是否是真实候选人 |

| 输出 | 用途 |
|---|---|
| `RouterOutput.conditions` | 补齐/清理后的 raw conditions |
| `RouterOutput.normalized_conditions` | 给 execution_policy、planner、compiler、validator 使用的标准条件 |

## 主流程

```text
normalize_router_output
-> _merge_candidate_reference_conditions
-> normalize_conditions
-> mark_preference_targets
-> _drop_context_reference_candidate_names
-> RouterOutput
```

每一步的作用：

| 阶段 | 作用 |
|---|---|
| out_of_scope fast path | 非简历问题清空 conditions / normalized_conditions |
| raw fallback | router 没给 conditions 时调用 `extract_conditions(question)` |
| candidate merge | 显式候选人名字补成 `candidate_name` condition |
| normalize | raw `QueryCondition` 转成 `NormalizedCondition` |
| preference target | 标记“适合做什么/推荐谁做什么”里的目标条件 |
| context cleanup | 删除被误抽成候选人名的“第一名/这些人”等上下文词 |

## 它做什么 / 不做什么

能做：

```text
补 raw conditions
合并显式候选人名字
标准化 domain / skill / concept / major / scope / candidate_name
标记 preference target
清理上下文引用误抽取
```

不能做：

```text
不改 intent
不改 scenario_decisions
不选工具
不调用 tools
不生成答案
```

## 怎么保证条件稳定

| 机制 | 作用 |
|---|---|
| router conditions 优先 | 保留上游已经识别的 raw conditions |
| extract fallback | 上游漏条件时再抽一次 |
| shared taxonomy | 用统一领域/技能/概念表标准化 |
| candidate merge | 候选人名字来自候选人识别/数据层，不混进 taxonomy |
| preference target | 避免“适合做金融风控”的目标条件被误当硬筛选 |
| context cleanup | 避免“第一名/这些人”被当作真实 candidate_name |

## 文档阅读顺序

```text
1. README.md
2. CONDITION_FLOW.md
3. YAML_USAGE.md
4. condition_normalizer.py
```

三份文档分工：

| 文档 | 作用 |
|---|---|
| `README.md` | 总览入口：节点在架构中做什么、边界是什么 |
| `CONDITION_FLOW.md` | 代码阅读线：按函数顺序读实现 |
| `YAML_USAGE.md` | YAML / taxonomy 使用地图 |

## 验收

```bash
./.venv/bin/python -m compileall -q resume_query_ai_qa/nodes/condition_normalizer
./.venv/bin/python resume_query_ai_qa/benchmarks/run_policy_contract_benchmark.py
./.venv/bin/python resume_query_ai_qa/benchmarks/run_plan_contract_benchmark.py
```
