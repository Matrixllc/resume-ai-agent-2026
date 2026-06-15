# Core Package

`core` 是 Query-AI 的共享底座。

一句话：

```text
core = schema 合同 + config facade + deterministic rules + inspection + answer generation + LLM client + read-only data access
```

它给 `graph`、`nodes`、`tools` 提供稳定对象和规则能力，但自己不编排 graph、不执行工具、不作为 node 运行。

## 架构位置

```text
user question
-> graph
-> nodes
-> core schemas/config/rules/inspection/answer_generation/llm
-> tools
-> nodes
-> graph final
```

依赖方向应该保持：

```text
graph / nodes / tools  -> core
core                  -> configs / shared_taxonomy / read-only data
core                  -> 不 import graph / nodes / tools
```

## 它做什么

- 定义全链路 Pydantic schema。
- 加载 YAML/env，并提供 `ResumeQAConfig` 查询 facade。
- 做启动期 YAML 交叉引用校验。
- 提供跨 node 复用的确定性规则。
- 提供 QueryPlan / ToolResult 只读 inspection helper。
- 提供 aggregator 真实答案生成核心逻辑。
- 提供 QA 自己的 LLM client 和 structured invoke。
- 提供 core 内部只读数据访问。

## 它不做什么

- 不运行 graph。
- 不选择下一个 node。
- 不直接执行 tool registry。
- 不修改 graph state。
- 不作为 plan/execution/answer validator 的替代入口。
- 不把 LLM 输出直接当最终事实。

## 子目录职责

| 路径 | 职责 | 主要联动 |
| --- | --- | --- |
| `schemas.py` | 全项目 Pydantic 合同：`RouterOutput`、`QueryPlan`、`ToolResult`、`AggregatedAnswer` 等 | graph、nodes、tools、benchmarks |
| `config/` | YAML/env 加载与 `ResumeQAConfig` 查询 facade | graph runner、nodes、core rules |
| `config_validation/` | 启动期 YAML / taxonomy 结构校验 | `load_config()` |
| `rules/` | 跨节点复用的确定性规则，不调用 LLM，不执行工具 | router、execution_policy、planner、compiler、repair |
| `rules/plan_building/` | QueryPlan 构建规则：tool binding、`$ref`、source policy、query args | plan_compiler、plan_repair、execution_repair |
| `inspection/` | 只读检查 helper：plan/artifact/result shape | compiler、validators、answer 侧 |
| `data_access/` | core 内部只读数据访问，主要用于规则信号和候选人索引 | candidate_mentions、tools helper、rule signals |
| `answer_generation/` | aggregator 真实核心：context、layout、grounding、rule draft、LLM fill/rewrite | aggregator、answer_rewrite、rule_answer_fallback |
| `llm/` | QA LLM 客户端和结构化调用合同 | router LLM、planner LLM、answer LLM |

## 边界

`core` 可以：

- import `core.schemas`
- import `core.config`
- 读取 `configs/` 和 `shared_taxonomy/`
- 在 `core.llm` 里调用配置好的 LLM provider
- 在 `core.data_access` 里做只读数据读取

`core` 不应该：

- import `resume_query_ai_qa.graph`
- import `resume_query_ai_qa.nodes`
- import `resume_query_ai_qa.tools`
- 执行工具函数
- 生成 graph route
- 私自维护另一套 YAML 对照表

## 阅读顺序

推荐先按这个顺序读：

```text
1. README.md
2. CORE_FLOW.md
3. schemas.py
4. config/README.md + config/CONFIG_FLOW.md
5. config_validation/README.md + config_validation/VALIDATION_FLOW.md
6. rules/README.md
7. rules/plan_building/README.md
8. inspection/README.md
9. data_access/README.md
10. answer_generation/README.md
11. llm/README.md
12. llm/client/README.md
```

## 运行时怎么联动

配置线：

```text
graph.run
-> load_config
-> ResumeQAConfig
-> validate_config_structure
-> nodes consume config query methods
```

规划线：

```text
router / execution_policy / planner / plan_compiler
-> core.rules
-> core.rules.plan_building
-> QueryPlan
```

校验线：

```text
plan_validator / execution_validator / answer_validator
-> core.inspection
-> core.rules.behavior_contract / evidence_policy
```

答案线：

```text
aggregator / answer_rewrite / rule_answer_fallback
-> core.answer_generation
-> core.llm when enabled
-> AggregatedAnswer
```

数据线：

```text
rules / tools helper
-> core.data_access
-> SQLite / vector index read-only access
```

## 排查地图

| 问题 | 优先看 |
| --- | --- |
| 字段对象看不懂 | `schemas.py` |
| YAML 不知道谁用 | `configs/README.md`、`config/README.md` |
| 配置引用报错 | `config_validation/README.md` |
| scenario / workflow 匹配不对 | `rules/execution_policy_rules.py` |
| SemanticPlan 不对 | `rules/semantic_plan.py` |
| ToolCallSpec 参数不对 | `rules/plan_building/README.md` |
| `$ref` / candidate source 不对 | `rules/plan_building/refs.py`、`source_policy.py` |
| validator 判断看不懂 | `inspection/README.md` |
| 答案事实乱 | `answer_generation/README.md` |
| LLM 输出 shape 不对 | `llm/client/README.md` |
| 候选人索引/底层数据读取不对 | `data_access/README.md` |

## 架构决策

当前不做大规模移动文件。

原因：

- `core` 子包已经按职责拆开。
- 真正缺的是总入口地图和阅读线。
- 移动文件会影响大量 import 和 benchmark，风险高。
- `schemas.py` 和 `config/model.py` 虽然大，但它们是集中合同/facade，拆开会让调用方更难找。

本轮只做：

- README / FLOW
- 子包 README
- `__init__.py` 模块说明

## 验收

```bash
rg "Core Package|CORE_FLOW|Rules Package|Plan Building|Answer Generation|LLM Package|Data Access|Inspection" resume_query_ai_qa/core
./.venv/bin/python -m compileall -q resume_query_ai_qa/core
./.venv/bin/python -c "from resume_query_ai_qa.core.config import load_config; load_config(); print('OK: load_config')"
./.venv/bin/python resume_query_ai_qa/benchmarks/run_architecture_contract_benchmark.py
./.venv/bin/python resume_query_ai_qa/benchmarks/run_policy_contract_benchmark.py
./.venv/bin/python resume_query_ai_qa/benchmarks/run_plan_contract_benchmark.py
./.venv/bin/python resume_query_ai_qa/benchmarks/run_runtime_contract_benchmark.py
```
