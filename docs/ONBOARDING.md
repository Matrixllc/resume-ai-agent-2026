# Query-AI 新人上手

这份文档是项目的单一新人入口。目标不是一次读完所有实现，而是在第一次接触项目时，
能回答三个问题：

1. 一次查询经过了哪些层？
2. 出问题时先看哪里？
3. 修改某类行为时应该改什么、跑什么测试？

## 先建立全局认识

Query-AI 是一条受约束的问答流水线，不是让 LLM 自由调用数据库的 Agent。

```text
用户问题
-> router：判断想做什么
-> condition_normalizer：统一领域、技能、候选人等条件
-> execution_policy：选择稳定 template 或 generic planner
-> planner（仅 generic）：描述语义步骤
-> plan_compiler：生成可执行 QueryPlan
-> plan_validator：检查计划是否合法
-> executor：调用只读工具
-> execution_validator：检查工具结果是否足够
-> aggregator：把工具事实写成答案
-> answer_validator：检查答案有没有改事实
-> final：写回会话上下文并结束
```

事实只能来自 `resume_query_tools`。LLM 可以帮助理解和表达，但不能直接查库，也不能改变
人数、名单、排名和证据。

## 模块地图

| 模块 | 负责 | 修改它的典型原因 |
| --- | --- | --- |
| `resume_query_v3` | 演示简历入库，写 SQLite/Chroma。 | 数据解析或标签生成有问题。 |
| `resume_query_tools` | 只读事实接口。 | 需要一种新的结构化查询能力。 |
| `resume_query_ai_qa/core` | schema、配置、纯规则、答案生成基础能力。 | 多节点共享契约需要变化。 |
| `resume_query_ai_qa/nodes` | 每个 graph 节点的具体职责。 | 某一层判断或处理需要变化。 |
| `resume_query_ai_qa/graph` | 节点注册和条件路由。 | 主链增加节点或路由。 |
| `resume_query_api` | HTTP DTO 和 trace diagnosis。 | API 展示字段需要变化。 |
| `resume_query_frontend_v3` | 展示答案和 Debug trace。 | 展示体验需要变化。 |

模块边界的 source of truth 是
[`resume_query_ai_qa/docs/NODE_BOUNDARIES.md`](../resume_query_ai_qa/docs/NODE_BOUNDARIES.md)。

## 完整示例：金融领域候选人有多少个，都有谁

问题：

```text
有多少个金融领域候选人，都有谁？
```

典型数据流：

1. `router` 识别为 compound，并拆出 `candidate_count`、`candidate_list`。
2. `condition_normalizer` 把“金融领域”归一化为 `Finance`。
3. `execution_policy` 选择稳定的 count/list workflow。
4. `plan_compiler` 生成同源计划：

```text
filter_candidates(domains_any=["Finance"]) -> candidate_pool
count_candidates(candidate_pool) -> candidate_count
```

5. `plan_validator` 检查 Finance 条件已被结构化工具消费，并确认 count/list 共用候选池。
6. `executor` 调用只读工具，返回候选人列表和人数。
7. `execution_validator` 检查两个结果都存在。
8. `aggregator` 从工具结果构造答案和 claims。
9. `answer_validator` 检查人数、人名和工具结果一致。
10. `final` 写回 `last_candidate_pool_*`，供“这些人里谁更好？”之类的追问使用。

运行并查看答案：

```bash
./.venv/bin/python resume_query_ai_qa/scripts/run_qa.py \
  "有多少个金融领域候选人，都有谁？" --answer-only --no-llm
```

查看最近运行：

```bash
./.venv/bin/python -m resume_query_ai_qa.scripts.query_logs list
./.venv/bin/python -m resume_query_ai_qa.scripts.query_logs show <trace_id>
```

## 六个核心概念

| 概念 | 含义 |
| --- | --- |
| `intent` | 用户要完成的目标，例如名单、画像、证据核查、排序。 |
| `scenario` | Router 对执行语义的判断，例如 `hard_filter`、`open_recall`、`fact_check`；规范来自 `configs/scenarios.yaml`。 |
| `QueryPlan` | validator 通过后 executor 唯一接受的工具执行计划。 |
| `ToolResult` | 工具返回的事实；最终答案必须能追溯到这里。 |
| `claim` | 答案中的结构化事实声明，用于校验人数、人名、排名和证据。 |
| `fallback/repair` | fallback 使用受控替代结果；repair 修改计划或答案后重新校验。 |

## 问题定位决策树

```text
intent、scenario 或上下文理解错
-> 看 router、condition_normalizer、intents.yaml、scenarios.yaml 和 Router prompt

工具选错、参数错、候选池范围错
-> 看 execution_policy、plan_compiler、plan_validator、compiler_templates.yaml、tool_policy.yaml

工具返回的数据不对
-> 看 resume_query_tools 和 SQLite/Chroma 数据

最终答案表达或事实不对
-> 看 aggregator、answer_layouts.yaml、answer_validator

发生 fallback / repair
-> 用 trace_id 运行 query_logs show，先看“发生了什么”和“建议检查”
```

## 三个新人练习

### 练习 1：查询并读取日志

运行上面的金融候选人问题，取得 trace ID，然后运行：

```bash
./.venv/bin/python -m resume_query_ai_qa.scripts.query_logs show <trace_id>
```

应能解释：intent、执行路径、工具结果、validator 结果、最终答案。

### 练习 2：新增一种已有 intent 的问法

目标：让一个新的名单问法仍识别为 `candidate_list`。

- 优先修改：`configs/router_rules.yaml` 或 `configs/intents.yaml`。
- 预期 trace：router intent 改变，但工具和答案契约不变。
- 必跑：

```bash
./.venv/bin/python resume_query_ai_qa/benchmarks/run_policy_contract_benchmark.py
./.venv/bin/python resume_query_ai_qa/benchmarks/run_plan_contract_benchmark.py
```

常见错误：只改 example，没有修改真正被规则读取的字段。

### 练习 3：调整答案布局

目标：调整某类答案章节顺序，但不改变事实。

- 优先修改：`configs/answer_layouts.yaml`。
- 预期 trace：`answer_layout` 不变或按预期变化，claims 和工具结果保持一致。
- 必跑：

```bash
./.venv/bin/python resume_query_ai_qa/benchmarks/run_runtime_contract_benchmark.py
./.venv/bin/python resume_query_ai_qa/benchmarks/run_runtime_contract_benchmark.py
```

常见错误：layout 要求了 grounded context 中不存在的信息。

## 推荐阅读顺序

1. 本文。
2. [`CHANGE_GUIDE.md`](CHANGE_GUIDE.md)。
3. [`resume_query_ai_qa/README.md`](../resume_query_ai_qa/README.md)。
4. [`resume_query_ai_qa/docs/NODE_BOUNDARIES.md`](../resume_query_ai_qa/docs/NODE_BOUNDARIES.md)。
5. [`QUERY_AI_LOGS.md`](../QUERY_AI_LOGS.md)。
6. 只在需要深挖时阅读节点 README 和 `FIELD_FLOW_REFERENCE.md`。

`resume_query_ai_qa/TASK_SUMMARY.md` 是历史实施记录，不是当前行为的 source of truth。
