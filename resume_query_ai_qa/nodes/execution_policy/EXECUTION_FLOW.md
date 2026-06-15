# Execution Policy Flow

这份文档只讲代码阅读线。YAML 字段地图看 `YAML_USAGE.md`，节点总览看 `README.md`。

## 入口阅读线

```text
resolve_execution_policy
-> resolve_execution_decision
-> route_after_execution_policy
```

`execution_policy.py` 是 graph node 的薄入口。真正规则在 `core/rules/execution_policy_rules.py`。

## 1. resolve_execution_policy

输入：

- `question`
- `router_output`
- `config`

输出：

- `ExecutionDecision`

为什么这么做：

- graph node 只需要一个稳定入口。
- 具体规则下沉到 `core/rules`，方便 benchmark、compiler、validator 共用。

## 2. resolve_execution_decision

代码阅读顺序：

```text
_router_intents(router_output)
-> scenario_for_intent(router_output, intent)
-> config.compiler_flags()
-> match_workflow(router_output, scenarios, config)
-> ExecutionDecision(...)
```

职责：

- 收集本轮 intent 和 scenario。
- 读取 compiler mode。
- 判断 template/generic。
- 不生成工具参数。

核心分支：

```text
mode == generic_tool_binding
-> 强制 generic

workflow_name 命中，或 mode == workflow_template
-> workflow_template

否则
-> generic_tool_binding
```

## 3. _router_intents

输入：

- `RouterOutput.intent`
- `RouterOutput.sub_intent_candidates`

输出：

- intent 列表

规则：

```text
intent == compound
-> 使用 sub_intent_candidates

其他
-> 使用单个 intent
```

为什么这么做：

- compound 问题需要把每个子 intent 的 scenario 都传给后续节点。

## 4. scenario_for_intent

输入：

- `router_output.scenario_decisions`
- `intent`

输出：

- scenario 字符串

职责：

- 只读取 router/finalizer 已经确定的 scenario。
- 不重新理解用户问题。

## 5. match_workflow

输入：

- `router_output`
- `scenarios`
- `config.compiler_templates.workflows`

输出：

- 命中的 workflow 名称，或者空字符串

执行过程：

```text
读取 workflows
-> 按 priority 从高到低排序
-> 逐个取 workflow.match
-> _workflow_matches(...)
-> 第一个命中就返回 workflow name
-> compound 且所有子 intent 都有可组合 workflow 时，返回 composed_sub_intent_workflows
-> 都没有命中，返回 ""
```

为什么按优先级：

- 复合稳定路径通常比单 intent template 更具体，应该优先命中。

## 6. _workflow_matches

这是 workflow 是否命中的核心函数。

判断规则：

```text
match.intent
-> 如果配置了，必须等于 router_output.intent

match.intents
-> 如果配置了，router_output.intent 必须在列表内

match.required_sub_intents
-> 如果配置了，必须全部包含在 router_output.sub_intent_candidates

match.scenarios
-> 如果配置了，当前 scenarios 至少有一个在列表内

match.requires_scope
-> 如果为 true，必须 _has_required_scope(router_output)
```

注意：

```text
workflow.match 里没写的字段不会检查。
所有写了的字段都通过，才算命中。
```

## 7. _has_required_scope

输入：

- `router_output.context_policy`
- `router_output.normalized_conditions`

返回 true 的情况：

- 上下文引用是 `candidate_pool`。
- 或者存在标准化范围条件：
  - `domain`
  - `skill`
  - `concept`
  - `keyword`
  - `major`
  - `job_intent`

排除：

- `matched_by` 以 `preference_target:` 开头的条件。

为什么排除 preference target：

- “推荐谁做金融风控”里的“金融风控”更像评分目标，不一定是硬筛选范围。

## 8. route_after_execution_policy

输入：

- `ExecutionDecision`

输出：

- graph 边标签：`template` 或 `generic`

规则：

```text
decision.compiler == workflow_template
-> template

其他
-> generic
```

## 示例

问题：

```text
金融候选人有几个，谁最强，依据是什么？
```

上游可能产出：

```text
intent = compound
sub_intent_candidates = [candidate_count, candidate_ranking, evidence_question]
normalized_conditions = [domain: 金融]
```

匹配过程：

```text
match_workflow
-> 先看 priority=100 的 scoped_count_rank_evidence
-> intent == compound，通过
-> required_sub_intents 三个都存在，通过
-> requires_scope == true，domain: 金融存在，通过
-> 返回 workflow_name = scoped_count_rank_evidence
```

最终：

```text
ExecutionDecision.compiler = workflow_template
ExecutionDecision.workflow_name = scoped_count_rank_evidence
graph route = template
```
