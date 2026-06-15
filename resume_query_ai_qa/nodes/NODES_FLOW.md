# Nodes Flow

## 这份文档看什么

`NODES_FLOW.md` 是从头到尾读 Query-AI graph 的阅读路线。

它回答：

```text
从哪个文件开始看？
每个阶段读哪个 node？
正常路径、repair 路径、answer fallback 路径分别怎么走？
遇到问题该跳到哪个节点文档？
```

节点功能总览见 `README.md`。每个节点内部细节见各自目录的 `README.md`、`*_FLOW.md`、`YAML_USAGE.md`。

## 0. 先读 Graph 骨架

第一层不要先进某个 node，先看 graph 怎么串：

```text
resume_query_ai_qa/graph/build.py
-> resume_query_ai_qa/graph/nodes.py
-> resume_query_ai_qa/graph/routes.py
-> resume_query_ai_qa/graph/state.py
```

### `graph/build.py`

看什么：

```text
注册了哪些节点
节点之间有哪些普通 edge
哪些节点后面有 conditional edge
repair/fallback 是否回 validator
```

核心顺序：

```text
START
-> router
-> condition_normalizer
-> execution_policy
-> planner? / plan_compiler
-> plan_validator
-> executor
-> execution_validator
-> aggregator
-> answer_validator
-> final
```

### `graph/nodes.py`

看什么：

```text
每个 graph node 怎么调用 nodes/* 包
读哪些 state 字段
写回哪些 state 字段
trace 记录什么
```

### `graph/routes.py`

看什么：

```text
execution_policy 后走 template 还是 generic
plan_validator 后走 execute / repair / clarify / fail
execution_validator 后走 aggregate / repair / clarify / fail
answer_validator 后走 final / rewrite / fallback / fail
```

### `graph/state.py`

看什么：

```text
router_output
semantic_plan
execution_decision
current_*_errors
current_*_issues
*_repairs / answer_rewrites
max_*_repairs / max_answer_rewrites
```

## 1. 正常成功路径

适合从零理解主链：

```text
router
-> condition_normalizer
-> execution_policy
-> planner? / plan_compiler
-> plan_validator
-> executor
-> execution_validator
-> aggregator
-> answer_validator
-> final
```

### 1.1 router

阅读顺序：

```text
router/README.md
-> router/ROUTER_FLOW.md
-> router/YAML_USAGE.md
-> router/node.py
```

看懂什么：

```text
用户自然语言怎么变成 RouterOutput
intent/scenario/conditions/context/requires flags 从哪里来
LLM draft、rule fallback、guard、finalizer 怎么收口
```

### 1.2 condition_normalizer

阅读顺序：

```text
condition_normalizer/README.md
-> condition_normalizer/CONDITION_FLOW.md
-> condition_normalizer/YAML_USAGE.md
```

看懂什么：

```text
raw conditions 怎么变成 normalized_conditions
domain/skill/concept/major/scope 怎么标准化
candidate_name 为什么单独处理
```

### 1.3 execution_policy

阅读顺序：

```text
execution_policy/README.md
-> execution_policy/EXECUTION_FLOW.md
-> execution_policy/YAML_USAGE.md
```

看懂什么：

```text
怎么匹配 workflow
什么时候走 template
什么时候走 generic planner
ExecutionDecision 给后续什么信息
```

### 1.4 planner

只在 generic 路径读。

阅读顺序：

```text
planner/README.md
-> planner/PLANNER_FLOW.md
-> planner/YAML_USAGE.md
```

看懂什么：

```text
RouterOutput + ExecutionDecision 怎么变成 SemanticPlan
semantic needs / tool hints 是什么
planner 和 plan_compiler 为什么分开
```

### 1.5 plan_compiler

阅读顺序：

```text
plan_compiler/README.md
-> plan_compiler/PLAN_COMPILER_FLOW.md
-> plan_compiler/YAML_USAGE.md
```

看懂什么：

```text
SemanticPlan / workflow 怎么变成 QueryPlan
ToolCallSpec 怎么生成
$binding 怎么变成 filter_args
$ref / output_key / depends_on 怎么安排
```

### 1.6 plan_validator

阅读顺序：

```text
plan_validator/README.md
-> plan_validator/PLAN_VALIDATOR_FLOW.md
-> plan_validator/YAML_USAGE.md
```

看懂什么：

```text
执行前检查哪些合同
为什么程序生成的 plan 仍然要 validate
哪些问题 repair，哪些 clarify/fail
```

### 1.7 executor

阅读顺序：

```text
executor/README.md
-> executor/EXECUTOR_FLOW.md
-> executor/YAML_USAGE.md
```

看懂什么：

```text
QueryPlan 如何按顺序执行
tool_context 怎么保存前面工具输出
后续工具怎么用 $ref 取前面结果
异常怎么包装成 failed ToolResult
```

### 1.8 execution_validator

阅读顺序：

```text
execution_validator/README.md
-> execution_validator/EXECUTION_VALIDATOR_FLOW.md
-> execution_validator/YAML_USAGE.md
```

看懂什么：

```text
ToolResult[] 是否满足计划和问题
count/ranking/compare/evidence/lineage 怎么检查
empty retrieval 怎么转成 repair/fail
```

### 1.9 aggregator

阅读顺序：

```text
aggregator/README.md
-> aggregator/AGGREGATOR_FLOW.md
-> aggregator/YAML_USAGE.md
```

看懂什么：

```text
ToolResult[] 怎么变成 AggregatedAnswer
YAML answer framework 怎么用
LLM answer 文本和 grounded claims 怎么合并
render_grounded_answer 为什么每次都先执行
```

### 1.10 answer_validator

阅读顺序：

```text
answer_validator/README.md
-> answer_validator/ANSWER_VALIDATOR_FLOW.md
-> answer_validator/YAML_USAGE.md
```

看懂什么：

```text
最终答案如何校验 count/ranking/name/evidence/layout/privacy
它校验 grounded claims + 部分 answer 文本
它不是完整逐句事实核验器
```

## 2. Plan / Execution Repair 路径

当正常路径中 validator 失败时读这条。

### 2.1 Plan repair

路径：

```text
plan_compiler
-> plan_validator
-> plan_repair
-> plan_validator
```

阅读顺序：

```text
plan_validator/README.md
-> plan_validator/PLAN_VALIDATOR_FLOW.md
-> plan_repair/README.md
-> plan_repair/PLAN_REPAIR_FLOW.md
-> plan_repair/YAML_USAGE.md
```

看懂什么：

```text
plan_validator 发现非法 QueryPlan
graph 根据 issue action 决定 repair/clarify/fail
plan_repair 基于 RouterOutput 确定性重建 QueryPlan
修完必须回 plan_validator
```

### 2.2 Execution repair

路径：

```text
executor
-> execution_validator
-> execution_repair
-> plan_validator
-> executor
```

阅读顺序：

```text
execution_validator/README.md
-> execution_validator/EXECUTION_VALIDATOR_FLOW.md
-> execution_repair/README.md
-> execution_repair/EXECUTION_REPAIR_FLOW.md
-> execution_repair/YAML_USAGE.md
```

看懂什么：

```text
execution_validator 发现 ToolResult 不满足合同
execution_repair 只修 open_recall + empty_retrieval + fallback_tool
repair 后不是直接执行，而是回 plan_validator
```

## 3. Answer Rewrite / Fallback 路径

当答案没通过 `answer_validator` 时读这条。

路径：

```text
aggregator
-> answer_validator
-> answer_rewrite
-> answer_validator
-> rule_answer_fallback?
-> answer_validator
```

阅读顺序：

```text
aggregator/README.md
-> aggregator/AGGREGATOR_FLOW.md
-> answer_validator/README.md
-> answer_validator/ANSWER_VALIDATOR_FLOW.md
-> answer_rewrite/README.md
-> answer_rewrite/ANSWER_REWRITE_FLOW.md
-> answer_rewrite/YAML_USAGE.md
-> rule_answer_fallback/README.md
```

看懂什么：

```text
aggregator 生成答案
answer_validator 发现 count/ranking/layout/privacy/evidence 等问题
answer_rewrite 生成 rewrite candidate 或请求 rule fallback
rewrite/fallback 后都必须回 answer_validator
```

注意：

```text
answer_rewrite 的 rule_repair 不是本节点直接修答案。
它会请求 rule_answer_fallback 生成确定性答案。
```

## 4. Clarification / Terminal 路径

当 graph 判断需要用户补信息时读这条。

路径：

```text
plan_validator / execution_validator
-> clarification
-> END
```

阅读顺序：

```text
clarification/README.md
-> session_context/README.md
-> graph/nodes.py clarification_node
```

看懂什么：

```text
哪些错误可以向用户澄清
候选人选项和上下文缺失说明怎么生成
为什么 clarification 不修 plan、不执行工具、不回答业务问题
```

## 5. 按问题排查怎么读

### intent / scenario 错

读：

```text
router/README.md
router/ROUTER_FLOW.md
router/YAML_USAGE.md
```

重点：

```text
LLM draft / rule fallback / guard / finalizer
intents.yaml / scenarios.yaml / router_rules.yaml
```

### condition 错

读：

```text
condition_normalizer/README.md
condition_normalizer/CONDITION_FLOW.md
condition_normalizer/YAML_USAGE.md
```

重点：

```text
extract_conditions
normalize_conditions
shared_taxonomy
candidate_name special handling
```

### workflow 路由错

读：

```text
execution_policy/README.md
execution_policy/EXECUTION_FLOW.md
plan_compiler/YAML_USAGE.md
```

重点：

```text
compiler_templates.yaml.workflows.*.match
intent / scenario / requires_scope
```

### ToolCallSpec 参数错

读：

```text
plan_compiler/PLAN_COMPILER_FLOW.md
plan_compiler/YAML_USAGE.md
plan_validator/PLAN_VALIDATOR_FLOW.md
```

重点：

```text
$binding
filter_args
$ref
depends_on
output_key
tool registry signature
```

### executor 工具执行错

读：

```text
executor/EXECUTOR_FLOW.md
executor/YAML_USAGE.md
execution_validator/EXECUTION_VALIDATOR_FLOW.md
```

重点：

```text
tool_context
bind_argument_refs
execute_tool_call_with_retry
failed ToolResult
```

### 工具结果不满足问题

读：

```text
execution_validator/README.md
execution_validator/EXECUTION_VALIDATOR_FLOW.md
execution_repair/EXECUTION_REPAIR_FLOW.md
```

重点：

```text
required tool results
evidence coverage
count mismatch
candidate lineage
empty retrieval
```

### 答案乱说或 layout 错

读：

```text
aggregator/AGGREGATOR_FLOW.md
answer_validator/ANSWER_VALIDATOR_FLOW.md
answer_rewrite/ANSWER_REWRITE_FLOW.md
```

重点：

```text
grounded_context
rule_draft
merge_grounding
claims / used_evidence_refs
count/ranking/layout/privacy checks
```

### 上下文引用错

读：

```text
router/ROUTER_FLOW.md
condition_normalizer/CONDITION_FLOW.md
plan_compiler/PLAN_COMPILER_FLOW.md
session_context/README.md
```

重点：

```text
context_policy
candidate reference cleanup
session_context
resolve_candidate_reference
```

## 6. YAML 阅读顺序

如果是第一次读配置，建议按这条线：

```text
router/YAML_USAGE.md
-> condition_normalizer/YAML_USAGE.md
-> execution_policy/YAML_USAGE.md
-> planner/YAML_USAGE.md
-> plan_compiler/YAML_USAGE.md
-> plan_validator/YAML_USAGE.md
-> executor/YAML_USAGE.md
-> execution_validator/YAML_USAGE.md
-> execution_repair/YAML_USAGE.md
-> aggregator/YAML_USAGE.md
-> answer_validator/YAML_USAGE.md
-> answer_rewrite/YAML_USAGE.md
```

不要从 YAML 文件本身硬读起。先看每个节点到底消费哪些字段，再回到配置文件看细节。

## 7. 最小读法

如果只是想快速掌握主链，按这个读：

```text
nodes/README.md
graph/build.py
graph/routes.py
router/README.md
condition_normalizer/README.md
execution_policy/README.md
plan_compiler/README.md
plan_validator/README.md
executor/README.md
execution_validator/README.md
aggregator/README.md
answer_validator/README.md
```

如果要能改代码，再补：

```text
每个节点的 *_FLOW.md
每个节点的 YAML_USAGE.md
graph/nodes.py
core/schemas.py
core/config.py
tools/registry.py
```

## 8. 验收命令

```bash
rg "Query-AI Nodes|NODES_FLOW|router|answer_rewrite|rule_answer_fallback|YAML" resume_query_ai_qa/nodes/README.md resume_query_ai_qa/nodes/NODES_FLOW.md
./.venv/bin/python -m compileall -q resume_query_ai_qa/nodes
./.venv/bin/python resume_query_ai_qa/benchmarks/run_policy_contract_benchmark.py
./.venv/bin/python resume_query_ai_qa/benchmarks/run_plan_contract_benchmark.py
./.venv/bin/python resume_query_ai_qa/benchmarks/run_runtime_contract_benchmark.py
```
