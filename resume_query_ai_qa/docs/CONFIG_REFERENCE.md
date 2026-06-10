# Config Reference

`resume_query_ai_qa/configs/` 是 QA Agent 的配置层。本轮不拆目录，所有 YAML 继续统一放在这个文件夹下，方便部署和运营查找。

核心原则：

> 能配置的稳定规则尽量放 YAML；代码只负责读取、校验和执行 contract。

`load_config()` 会在启动时执行跨文件结构校验。未知 intent、未知 scenario、非法
intent/scenario 组合、未知工具、workflow/layout
无效引用和 required section 缺失会直接抛出包含配置文件名与引用路径的可读错误，避免
问题运行到 compiler 或 aggregator 才暴露。

## 配置总览

| 文件 | 主要使用方 | 作用 |
|---|---|---|
| `intents.yaml` | router / validator | 定义 intent、compound、证据/JD 要求 |
| `scenarios.yaml` | router / execution_policy / validator | scenario 唯一定义、允许 intent、说明和示例 |
| `router_rules.yaml` | router | query preprocess、rule fallback、上下文指代和敏感问题 |
| `compiler_templates.yaml` | execution_policy / plan_compiler | 稳定 workflow template |
| `tool_policy.yaml` | generic compiler / validator | 工具白名单、推荐工具、禁用工具 |
| `answer_layouts.yaml` | aggregator | 答案 layout、必需章节、表达规则 |
| `validation.yaml` | validators / runner repair | plan/execution/answer 边界 |
| `evidence_policy.yaml` | evidence validator / answer validator | 每类 intent 的证据要求 |
| `jd_scoring.yaml` | scoring tools | JD 评分维度和默认规则 |
| `llm.yaml` | router/planner/aggregator LLM wrapper | provider、model、temperature、timeout |

## `intents.yaml`

它回答：系统认识哪些用户目标。

常见字段：

- `description`：这个 intent 表示什么。
- `allow_compound`：是否允许出现在复合问题里。
- `requires_jd_criteria`：是否需要 JD 标准。
- `requires_evidence`：是否需要证据。
- `semantic_needs`：rule planner 为该 intent 生成的语义需求列表。
- `scenario_defaults`：同一 intent 在不同 scenario 下的默认要求。
- `examples`：给运营和 benchmark 看，不是执行逻辑本身。

什么时候改：

- 新增一种问题目标，比如新增“生成候选人风险报告”。
- 调整某个 intent 是否需要证据或 JD。
- 让 compound 问题可以包含某个新 intent。

注意：

新增 intent 只改 YAML 不够，还要检查 `IntentName` schema、router、compiler、validator 和 benchmark。

## `router_rules.yaml`

它回答：router 在 LLM 之外有哪些确定性边界。

核心字段：

- `preprocess`：轻量清理用户问题。
- `out_of_scope`：通用知识问题和简历检索信号。
- `intent_rules`：rule fallback 的关键词/句式。
- `compound_rules`：count/list/ranking/evidence 子任务触发词。
- `signals`：project、experience、profile、fit、open recall 等通用信号词。
- `pair_compare`：双人比较连接词、比较词和排序排除词。
- `resume_domain`：简历领域准入词，避免 `Python 是什么？` 这类通用知识问题误查 tools。
- `context_references`：`他/这些人/第一名/这个岗位` 等上下文指代。
- `context_resolution.current_turn_outputs`：声明某个 intent 在本轮生成的引用类型；用于区分“本轮第一名是谁”和“上一轮第一名有哪些项目”。
- `sensitive_interview_terms`：年龄、性别、婚育、民族、政治面貌、照片等敏感边界。
- `intent_reasons`：router 输出 sub intent evidence 的 reason 文案。
- `risk_flags.allowed_prefixes`：finalizer 保留的风险标记白名单。

什么时候改：

- 调整 LLM 不可用时的 rule fallback 问法。
- 某类 out_of_scope 被误查简历 tools。
- 新增上下文指代表达。
- 敏感问题需要增加拦截词。

不要用它做：

- 生成工具参数。
- 定义正常路径的 intent 或 scenario。
- 定义答案 layout。

## `compiler_templates.yaml`

它回答：哪些稳定问题可以跳过 planner，用固定 workflow 快速编译。

核心字段：

- `workflows`：workflow 名称。
- `priority`：多个 workflow 都可能命中时的优先级。
- `match.intents`：支持哪些 intent。
- `match.required_sub_intents`：compound workflow 需要哪些子 intent。
- `match.scenarios`：支持哪些 scenario。
- `tool_calls`：固定工具链。
- `artifact_type` / `default_output_key`：工具产物如何绑定。

典型例子：

`介绍一下孟连星` 通常是：

```text
intent=candidate_profile_intro
scenario=soft_summary
workflow=candidate_profile_intro
```

命中后跳过 planner，compiler 直接生成候选人解析和画像工具调用。

什么时候改：

- 高频问题已经跑稳定，可以沉淀成 template。
- 复杂 compound 需要保证同源，比如 count + rank + evidence。
- 希望减少 LLM planner 成本和不确定性。

不要用它做：

- 开放探索问题的所有可能变体。
- 临时兜底逻辑。
- 与工具能力无关的自然语言判断。

## `tool_policy.yaml`

它回答：generic compiler 在某个 intent/scenario 下允许用哪些工具。

核心字段：

- `tools`：工具元信息，描述产物、消费、scope。
- `intent_tools`：intent 到工具策略的映射。
- `allowed_tools`：允许工具。
- `preferred_tools`：优先工具。
- `forbidden_tools`：禁用工具。
- `scenarios`：不同 scenario 下覆盖工具策略。

工作方式：

LLM planner 可能输出 tool hints，但 generic compiler 不会照单全收。它会检查：

```text
tool 是否在 registry
tool 是否被 intent/scenario 允许
tool 是否和 source scope 冲突
tool 是否能产出下游需要的 artifact
```

什么时候改：

- 新工具上线。
- 某个开放问题要允许 evidence/search。
- 某个 scenario 下要禁止全库工具。

## `answer_layouts.yaml`

它回答：工具结果应该用什么结构表达。

核心字段：

- `layouts`：layout 名称。
- `priority`：匹配优先级。
- `required_tools`：什么工具结果存在时可用。
- `sections`：layout 可包含的语义章节。
- `required_sections`：必须回答的语义内容，不等于必须显示章节标题。
- `titles`：section 对应的可见标题文本。
- `required_title_sections`：必须显示 `titles` 中标题的章节。
- `first_section`：必须位于答案开头的章节。
- `prompt_template`：LLM polish 的表达指导。
- `rules`：不能违反的排版规则。

注意：

layout 只能改变表达方式，不能改变事实。人数、名单、排名、证据仍以 tools 为准。
默认 layout 可以只给出自然语言结论；结构化 layout 是否强制显示标题和顺序，完全由
`required_title_sections` 与 `first_section` 决定。

什么时候改：

- 新增“候选人对比表”“面试题列表”“决策链路”这类答案结构。
- 调整展示顺序或必需章节。

## `validation.yaml`

它回答：哪些行为必须被拦截，哪些错误可以 repair。

内容包括：

- retry 上限。
- compare 人数边界。
- ranking 是否必须有 JD criteria、score、rank。
- answer 是否必须来自 tools。
- 隐私字段和敏感字段。

什么时候改：

- 部署后发现某类 bad case 应该更早拦截。
- 调整隐私策略。
- 调整 retry/repair 上限。

## `evidence_policy.yaml`

它回答：不同 intent 最少需要什么证据。

典型规则：

- `candidate_count` 不要求 evidence，但必须有 tool count。
- `candidate_profile_intro` 需要候选人相关证据。
- `candidate_ranking` 需要 scoring table 和 evidence。
- `candidate_filter` 在 `hard_filter` 下可以只用结构化标签，在 `evidence_lookup` 下需要证据。

什么时候改：

- 某个 intent 的证据要求变化。
- 调整项目证据、标签、工作经历之间的强弱关系。

## `jd_scoring.yaml`

它回答：排序/推荐问题如何评分。

内容包括：

- 总分。
- 默认 JD 路径。
- 评分维度和权重。
- 缺 JD 时是否加载默认 JD。
- aggregator 是否允许解释但不能重排。

注意：

工具产出的 rank 是事实层排序，aggregator 不能因为表达需要改顺序。

## `llm.yaml`

它回答：LLM 节点用哪个 provider/model。

使用方：

- router LLM。
- planner LLM。
- aggregator polish / answer rewrite。

注意：

LLM 不可用时，系统应走 rule fallback。LLM 失败是可观测事件，会进入 trace 的 `fallback_reason`。

## 新增场景怎么选

| 目标 | 首选改动 |
|---|---|
| 高频稳定问法 | `compiler_templates.yaml` |
| 开放探索问法 | `tool_policy.yaml`，先走 generic |
| 新 intent | `intents.yaml` + schema/router/compiler/validator |
| 新工具 | tool 实现 + registry + `tool_policy.yaml` |
| 新答案结构 | `answer_layouts.yaml` |
| 新证据要求 | `evidence_policy.yaml` |
| 新排序口径 | `jd_scoring.yaml` |
| 新安全边界 | `validation.yaml` |

## 检查清单

改配置后至少确认：

- 新 intent 是否存在于 schema 和 benchmark。
- workflow 引用的 tool 是否在 registry。
- tool policy 没有允许越界工具。
- count/list/rank/evidence 是否共享候选池。
- answer layout 没有要求不存在的工具。
- bad case benchmark 仍能看到 validation error、fallback reason 或 clarification。
