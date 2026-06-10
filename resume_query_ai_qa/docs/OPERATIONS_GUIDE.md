# Operations Guide

这份文档面向后续新增场景、运营配置和部署维护。原则是：能改配置就不改代码，必须改代码时只改对应边界。

## 改动入口总表

| 你要做什么 | 优先改哪里 | 必补测试 |
|---|---|---|
| 新增高频稳定问法 | `configs/compiler_templates.yaml` | `run_plan_contract_benchmark.py` |
| 新增 intent | `core/schemas.py`、`configs/intents.yaml`、`configs/router_rules.yaml`、`nodes/router/` | router/context + hybrid + full-chain |
| 新增开放召回策略 | `configs/tool_policy.yaml` | semantic compiler + LLM full-chain |
| 新增工具 | `resume_query_tools`、`resume_query_ai_qa/tools/registry.py`、`configs/intents.yaml` | validator + executor smoke |
| 新增答案样式 | `configs/answer_layouts.yaml`、aggregator layout 逻辑 | boundary contract |
| 新增领域词/同义词 | `condition_normalizer` 的词表/规则 | structured filter + domain diversity |
| 调整安全边界 | `configs/validation.yaml`、validators | boundary contract |

## 新增 Workflow Template

适合：高频、流程稳定、工具顺序固定的问题。

步骤：

1. 在 `configs/compiler_templates.yaml` 添加 workflow。
2. 写清楚 `priority`、`match.intents` 或 `match.required_sub_intents`、`scenarios`。
3. 配置固定 tool calls 和 `default_output_key`。
4. 如果是特殊复合 workflow，在 `nodes/plan_compiler/templates.py` 添加专用编译函数。
5. 在 `run_plan_contract_benchmark.py` 加 case，确认命中 template 且跳过 planner。
6. 在 full-chain benchmark 加自然语言问题。

判断是否适合 template：

- 工具顺序基本不变。
- 结果必须严格可验证。
- 运营希望速度快、行为稳定。

## 新增 Generic 场景

适合：开放召回、描述性问题、过渡期新场景。

步骤：

1. 确认 router 能识别 intent 或 compound。
2. 在 `tool_policy.yaml` 配置 scenario 下允许/推荐工具。
3. 在 `scenarios.yaml` 配置 intent/scenario 允许关系、planner 类型和 rule fallback 规则。
4. 让 `planner` 生成 `SemanticPlan`。
5. 让 `plan_compiler` 绑定合法 tool calls。
6. 补 full-chain case，确认 validator 没放过越界工具。

## 新增 Intent

只有在现有 intent 无法表达问题目标时才新增。

必须改：

1. `core/schemas.py` 的 `IntentName`。
2. `configs/intents.yaml` 的 intent、allowed tools、边界说明。
3. `router_rules.yaml` 或 router LLM prompt 的识别规则和 evidence。
4. `configs/intents.yaml` 的 `semantic_needs`，以及 `configs/tool_policy.yaml` 的 `preferred_tools`。
5. `configs/scenarios.yaml` 的 allowed intents、planner 和 rule fallback 规则；只有新增匹配算法时才改 `core/rules/execution_policy_rules.py`。
6. 必要时更新 `compiler_templates.yaml` 或 `tool_policy.yaml`。
7. benchmark：router/context、semantic compiler、hybrid/full-chain。

## 新增 Tool

工具必须是只读工具。

步骤：

1. 在 `resume_query_tools` 实现只读函数。
2. 在 `resume_query_ai_qa/tools/registry.py` 注册。
3. 在 `configs/intents.yaml` 或 `tool_policy.yaml` 允许该工具。
4. 在对应 validator 节点包加必要参数/边界校验：`nodes/plan_validator/`、`nodes/execution_validator/` 或 `nodes/answer_validator/`。
5. 在 `executor.py` 确认参数引用能被解析。
6. 补测试，至少覆盖正常参数、缺参数、越界参数。

## 新增答案 Layout

适合：同一类问题需要固定输出结构。

步骤：

1. 在 `configs/answer_layouts.yaml` 新增 layout。
2. 在 aggregator layout 推断逻辑里挂接规则。
3. 明确 section 顺序，例如 `结论 -> 数量 -> 推荐排序 -> 主要依据`。
4. 在 `run_plan_contract_benchmark.py` 加 layout case。
5. full-chain 中补一个真实 LLM case。

## 运营可读规则

给运营解释时不要讲内部函数名，讲四层：

1. 先判断问题类型。
2. 再判断能不能走稳定流程。
3. 再查候选人/证据/排序工具。
4. 最后只基于工具结果写答案。

每次新增场景都需要回答：

- 这个问题属于哪个 intent？
- 是稳定 template 还是 generic？
- 需要哪些 tools？
- 答案需要哪个 layout？
- 没有证据时怎么说？
- 是否涉及敏感/越界边界？

## 不建议做的事

- 不把所有新问法都塞进 router 硬规则。
- 不让 aggregator 自己判断事实。
- 不让 LLM 直接决定工具执行结果。
- 不为一次性问题加 workflow template。
- 不在 tools 层写业务回答文案。
