# Node Boundaries

这份文档用于阅读链路时快速判断：一个问题流到哪个节点，谁负责判断，谁不能越界。

## 主链路

```text
router
-> condition_normalizer
-> execution_policy
   -> workflow_template: plan_compiler
   -> generic_tool_binding: planner -> plan_compiler
-> plan_validator
-> executor
-> execution_validator
-> aggregator
-> answer_validator
-> final
```

## 节点职责表

| Node | 输入 | 输出 | 职责 | 禁止 |
|---|---|---|---|---|
| `router` | question、session context | `RouterOutput` | 判断 intent、compound、sub intents、scenario、context policy、risk flags；规则 helper 可通过 `core.data_access` 读取少量候选人姓名等规则信号 | 调用 tools / `get_tool_registry()`、生成 tool args、回答 |
| `condition_normalizer` | question、`RouterOutput.conditions` | normalized conditions | 统一领域、技能、候选人名、scope、检索词 | 改业务结论、选 workflow |
| `execution_policy` | question、normalized router output、compiler config | `ExecutionDecision` | 读取 router-owned scenario，决定 `workflow_template` 或 `generic_tool_binding`，记录调度原因 | 生成工具调用、重新判定 scenario、回答 |
| `planner` | question、router output、decision | `SemanticPlan` | 只在 generic 路径生成语义步骤和 tool hints | 直接产最终答案、直接调 tools |
| `plan_compiler` | question、router output、semantic plan、decision | `QueryPlan` | 把 template 或 generic 语义计划编译成 tool calls、artifact binding；可读取 `get_tool_registry()` 做工具协议绑定 | 判断用户 intent、执行 tools、直接查库或走 `core.data_access` |
| `plan_validator` | `QueryPlan`、router output、session context | validation result | 检查工具白名单、参数、scope、JD 依赖、上下文依赖；可读取 `get_tool_registry()` 做只读签名审查 | 修工具结果、生成答案、执行工具、直接查库或走 `core.data_access` |
| `plan_repair` | plan errors、previous plan | repaired `QueryPlan` | 根据错误类型走规则或 LLM repair | 放宽安全边界 |
| `executor` | validated `QueryPlan` | tool results | 调用只读工具，记录结果摘要 | 总结、重算排序、编造证据 |
| `execution_validator` | plan、tool results | validation result | 判断结果是否足够回答，如 count/list/rank/evidence 是否齐全 | 生成自然语言答案 |
| `execution_repair` | execution errors、tool results | repaired `QueryPlan` | 缺结果时补查或切换 fallback query | 跳过 plan validator |
| `aggregator` | question、plan、tool results、layout config | `AggregatedAnswer` | 基于工具结果组织中文答案 | 新增事实、改人数、改排名 |
| `answer_validator` | answer、tool results、plan | validation result | 校验人数、人名、证据、layout、比较结论可追溯 | 润色答案 |
| `answer_rewrite` | answer errors、previous answer | rewritten answer | 只修复 answer validator 指出的越界 | 重新规划或调工具 |
| `final` | validated state | final state | 更新 session context，结束链路 | 改答案内容 |

## 文件夹职责边界

| Folder | 负责 | 禁止 |
|---|---|---|
| `graph/` | LangGraph 注册、node 编排、条件路由、trace helper 调用 | 直接调用 tools、scoring、`core.data_access`，承载业务规则 |
| `state/` | session context 写回、trace event、route event、state snapshot | 判断业务路由、生成答案、执行工具 |
| `core/` | 公共 schema/config/rules/inspection/answer generation/plan 构造/LLM 基础设施；`core/rules/taxonomy.py` 是 QA 访问 `shared_taxonomy` 的唯一入口 | import `nodes`、`graph`、`tools` |
| `nodes/` | 单节点职责实现和节点私有 helper | 编排 graph、直接执行 sibling node 完整流程 |
| `tools/` | 只读事实工具和 registry | 生成最终答案、修改 graph state |
| `scoring/` | JD 评分和排序算法 | 写 graph trace、调用 graph node |
| `observability/` | 日志 sink、run summary、detail JSON | 修改业务状态、决定路由 |
| `benchmarks/` | 合同测试、边界验收、回归用例 | 承载生产逻辑 |

## 日志排查分工

| 日志 | 负责方 | 用途 |
|---|---|---|
| `logs/query_ai_events.jsonl` | `observability.emit_event` | 原子事件流，适合 tail 实时排查 |
| `logs/qa_runs.jsonl` | `observability.write_run_log` | 每次 run 的轻量索引，快速找 trace id 和失败节点 |
| `logs/<timestamp>_<trace_id>.json` | `observability.write_run_log` | 单次完整 detail，以 `decision_log`、`route_events` 为 canonical trace，并包含 `failed_at` |
| `trace.decision_log` | `state.record_node_decision` | 每个 node 的关键输入输出、engine、fallback、耗时 |
| `trace.route_events` | `state.record_route_decision` | 条件边跳转、route reason、retry count |
| `trace.state_snapshots` | `state.record_state_snapshot` | 每个 node 后的状态摘要 |

排查顺序：先用 `qa_runs.jsonl` 找 trace id，再打开 detail JSON 看 `decision_log` 和 `route_events`，失败时看 `failed_at`，最后回到对应 validator errors。

## 大文件拆分约定

- 生产代码单文件目标小于 300 行。
- 复杂契约文件可放宽到 450 行，但 README 必须解释结构和拆分原因。
- 超过 500 行的生产文件必须拆分；结构契约不接受永久 allowlist。
- 拆分优先按职责边界，不按“平均行数”机械切分。
- public API 保持在原包入口，避免大拆后影响调用方。

## 谁负责做判断

| 判断问题 | 负责节点 |
|---|---|
| 这是简历问题还是越界问题 | `router` |
| 是单 intent 还是 compound intent | `router` |
| 每个 intent 的 scenario 是 hard_filter、open_recall、fact_check 等哪一种 | `router` |
| “他”“这些人”“第一名”指什么 | `router` 初判，`resolve_candidate_reference` 工具落地 |
| 金融、运营、能源等词归一化 | `condition_normalizer` |
| 走 template 还是 generic | `execution_policy` |
| template 是否跳过 planner | `execution_policy` 的 conditional edge |
| generic 用 rule planner 还是 LLM planner | `execution_policy.planner` |
| 具体调用哪些工具 | `plan_compiler` |
| 工具参数是否合法 | `plan_validator` |
| 工具结果是否足够回答 | `execution_validator` |
| 答案该怎么排版 | `aggregator` 根据 `answer_layouts.yaml` |
| 答案有没有编造 | `answer_validator` |

## 规则真源

规则驱动不是“Python 里写完规则，再用 YAML 做说明”。运行时规则真源如下：

| 规则 | 真源 | Python 的职责 |
|---|---|---|
| intent 定义与默认语义需求 | `configs/intents.yaml` | Router 识别意图，finalizer 重算派生字段 |
| scenario 目录、rule fallback 决策、generic planner 类型 | `configs/scenarios.yaml` | 按固定优先级匹配条件，不维护 intent/scenario 对照表 |
| Router 触发词、上下文引用、敏感边界 | `configs/router_rules.yaml` | 提取信号并执行有序 guard |
| intent/scenario 可用工具和 binding kind | `configs/tool_policy.yaml` | Compiler 执行绑定，Validator 校验同一策略 |
| 稳定 workflow 与 tool call 顺序 | `configs/compiler_templates.yaml` | 将声明式模板编译为 `QueryPlan` |
| repair、重试与 validator 动作 | `configs/validation.yaml` | Validator 只报告，Repair 按结构化 issue 执行动作 |
| 答案任务和布局 | `configs/aggregator_tasks.yaml`、`configs/answer_layouts.yaml` | Renderer 只渲染已落地事实 |

`load_config()` 会在启动期交叉校验 intent、scenario、tool、workflow 和 layout 引用。
新增稳定规则应先修改对应 YAML；只有新增匹配能力、binding kind 或验证算法时才修改 Python。

`nodes/aggregator/` 仅保留历史导入兼容层，实际答案实现位于
`core/answer_generation/`，graph 直接依赖真实实现，避免误读为两套聚合逻辑。

### 配置事实与算法不变量

以下内容属于配置事实，不能在 Python 中维护第二份名称映射：

- intent 与 scenario 的合法组合、scenario planner 类型。
- 工具允许/禁用关系、工具角色、`binding_kind`、`produces`、默认输出 key。
- 稳定 workflow 的工具顺序、声明式参数引用、重试和 repair 动作。
- 答案任务类型、布局标题和可见顺序。

以下内容属于 Python 算法不变量，应保留为可读代码而不是继续配置化：

- Router 信号匹配与 guard 的执行优先级。
- 参数引用解析、候选池依赖链和 canonical source 一致性检查。
- 工具结果结构解析、证据覆盖率计算、JD 评分公式。
- Validator 发现问题但不修复、Repair 修复后必须重新校验等控制流约束。

兼容转发模块只用于旧 import 路径，生产代码禁止依赖：
`nodes/aggregator/*`、`nodes/plan_compiler/binding.py`、
`nodes/plan_compiler/artifacts.py`、`nodes/planner/rules.py`。该约束由
architecture contract 自动检查。

Repair 与 Validator 保持节点分离：Validator 永远只读，Repair 修改 `QueryPlan`
后必须刷新 artifact bindings，并重新进入 `plan_validator`。Repair LLM 代码保留
为实验能力，但 `configs/validation.yaml` 默认关闭；semantic error 默认使用
确定性 rule repair。

## 读 Trace 的顺序

1. 看 `trace.router_output.intent`、`sub_intent_candidates` 和 `scenario_decisions`。
2. 看 `trace.execution_decision`：`compiler`、`workflow_name`、从 router 透传的 `scenarios`、`reason`。
3. 看 decision log 是否出现 `planner`：出现代表 generic，没出现代表 template 快路径。
4. 看 `plan_compiler` 输出的 tool calls 和 artifact binding。
5. 看 validator errors，确认是否进入 repair。
6. 看 executor 的 tool result summary。
7. 看 aggregator 的 `answer_layout` 和 `aggregator_io_mode`。
8. 看 answer validator 是否通过。

## 常见问题流转

| 用户问题 | 典型流转 |
|---|---|
| `介绍一下孟连星` | router: `candidate_profile_intro` -> execution_policy: `candidate_profile_intro` template -> compiler -> tools |
| `有多少个金融领域候选人，都有谁？` | router: compound count/list -> generic/template composition -> filter source 共用 |
| `谁有金融背景？` | router: filter/evidence discovery -> generic planner -> generic compiler |
| `这些人里谁适合金融岗位？` | router: ranking + candidate_pool context -> compiler 绑定 context ids |
| `金融候选人有几个，谁最强，依据是什么？` | router: compound -> scoped count-rank-evidence workflow |
| `今天天气怎么样？` | router: out_of_scope -> no resume tools -> answer |

## Bad Case / Fallback 边界

异常链路也必须走 graph，这样前端和后端都能看到同一个 trace。

| Bad Case | 发现节点 | 处理 | Debug 字段 |
|---|---|---|---|
| 缺少 `last_candidate` | `plan_validator` | `fail` | `validation_errors.plan` |
| 缺少 `candidate_pool` | `plan_validator` | `fail` | `context_policy`, `validation_errors.plan` |
| 双人比较缺少明确两位候选人 | `plan_validator` / `execution_validator` | `clarification` | `validation_errors.plan` / `validation_errors.execution` |
| 工具不在白名单 | `plan_validator` | `plan_repair` 或 `fail` | `repair_action`, `repair_reason` |
| 工具执行失败 | `executor` / `execution_validator` | retry 或 `execution_repair` | `tools[].status`, `validation_errors.execution` |
| 工具结果不足 | `execution_validator` | 补查或 grounded empty answer | `execution_validation_errors` |
| LLM provider 失败 | 当前 LLM node | rule fallback | `fallback_reason` |
| 答案越界 | `answer_validator` | `answer_rewrite` 或 `rule_answer_fallback` | `validation_errors.answer` |
| 非简历问题 | `router` | out_of_scope，无工具 | `intent`, empty tools |

后端排查从前端 Trace ID 开始：

```bash
tail -n 20 resume_query_ai_qa/logs/qa_runs.jsonl
ls resume_query_ai_qa/logs/*<trace_id>*.json
python -m json.tool resume_query_ai_qa/logs/<timestamp>_<trace_id>.json | less
```
