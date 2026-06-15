# Query-AI Configs

`resume_query_ai_qa/configs/` 是 Query-AI 问答 graph 的稳定规则层。

一句话：

```text
.env = 运行时覆盖层，放密钥、provider、本机地址和少量开关
configs/*.yaml = 业务规则声明层，放 intent、scenario、workflow、工具策略和校验合同
core/config = YAML 加载与查询 facade
core/config_validation = 启动期合同校验
```

这里放的是规则和合同，不放 Python 执行逻辑。运行时节点不应该自己解析 YAML shape，而应该通过 `ResumeQAConfig` 的查询方法消费配置。

## 配置分层

### `.env`

`.env` 负责环境差异和敏感信息：

- `OPENAI_API_KEY`：真实密钥，只能放本地 `.env` 或部署 secret storage，不写进 README/YAML/log。
- `RESUME_V3_*`：Query V3 数据基座链路的 provider、embedding 等运行参数。
- `RESUME_QA_*`：Query-AI QA graph 的 LLM provider、模型和 compiler 开关。
- `OLLAMA_HOST`：本地 Ollama 服务地址，可能被本地模型和 embedding/向量读取共用。

### `configs/*.yaml`

YAML 负责稳定业务规则：

- 定义用户意图、场景、条件抽取和 router fallback。
- 定义稳定 workflow、工具策略、校验策略、答案结构和证据要求。
- 定义 JD scoring 口径和 QA LLM 默认值。
- 作为跨 node 共享合同，避免规则散落在节点代码里。

YAML 不负责：

- 不执行 graph。
- 不调用 tools。
- 不生成 `RouterOutput`、`QueryPlan` 或最终答案。
- 不保存密钥。
- 不表达本机/部署环境差异。

## 运行链路位置

```text
graph.run / benchmark / script
-> core.config.load_config
-> configs/*.yaml
-> ResumeQAConfig
-> core.config_validation.validate_config_structure
-> router / planner / compiler / executor / validators / answer generation
```

## YAML 文件说明

| 文件 | 管什么 | 不管什么 | 主要使用方 | 什么时候改 |
| --- | --- | --- | --- | --- |
| `intents.yaml` | 用户意图、semantic needs、是否需要 JD/证据、示例问题 | 不做具体路由判断，不生成工具调用 | router finalizer、planner、plan compiler、validator | 新增/调整用户问题类型，例如筛选、排序、画像、证据问答 |
| `scenarios.yaml` | 每个 intent 下的执行场景、允许 intent、planner 选择、scenario resolution rules | 不抽取条件，不绑定工具参数 | router finalizer、execution_policy、planner、validator | 区分严格筛选、开放召回、画像、事实核查、比较排序等场景 |
| `router_rules.yaml` | router 规则 fallback、越界判断、上下文/敏感信号、预处理词 | 不定义工具链，不做答案生成 | router、context resolver | 调整问题如何进入/拒绝 QA graph，或补充规则路由兜底 |
| `condition_rules.yaml` | 条件类型、正则抽取、taxonomy alias、preference target、filter argument 映射 | 不执行筛选，不查数据库 | condition_normalizer、router condition completion、plan_building | 调整领域/技能/专业/关键词等条件如何被识别和归一化 |
| `compiler_templates.yaml` | 稳定 workflow template、tool call 顺序、产物类型、依赖关系 | 不匹配用户原文，不执行工具 | execution_policy、plan_compiler、plan_validator | 把高频稳定问题沉淀成可控工具链，例如 count/list/profile/ranking |
| `tool_policy.yaml` | 工具 metadata、allowed/preferred/forbidden、binding_kind、产物输入输出合同 | 不实现工具函数，不访问存储 | planner、compiler、validator、repair、tools registry 对齐 | 新增工具、调整工具权限、修正工具之间的 source/produces/consumes 合同 |
| `validation.yaml` | retry 限制、issue action、plan/execution/answer 校验边界、repair 策略 | 不生成新计划，不修复 YAML | plan_validator、execution_validator、answer_validator、repair、executor retry | 调整失败如何处理，或收紧计划/执行/答案的合同 |
| `answer_layouts.yaml` | 答案 layout、section、标题、claim contract、证据展示策略 | 不决定检索什么数据，不调用 LLM | answer generation、aggregator、answer_validator | 调整最终回答结构，例如候选人块、比较表、证据段落 |
| `aggregator_tasks.yaml` | 答案任务类型、触发条件、生成模式、fallback policy、slot hints | 不验证工具结果，不改 layout 细节 | aggregator、answer generation | 调整“这类 QueryPlan 应该生成哪种答案任务” |
| `evidence_policy.yaml` | 证据强度顺序、各 intent 证据要求、空证据表达 | 不检索证据，不判断工具是否成功 | execution_validator、answer_validator、aggregator | 调整哪些问题必须给证据、每个候选人最少证据数、弱证据表达 |
| `jd_scoring.yaml` | JD 评分维度、权重、默认 JD 路径、评分规则 | 不读取简历，不替用户重排答案 | scoring、plan/compiler/validator 合同 | 调整 JD 匹配口径、评分权重、默认 JD 文件 |
| `llm.yaml` | QA LLM 默认 provider/model/base_url/temperature/timeout/retry | 不保存 API key，不覆盖 `.env` 已显式设置的运行值 | router/planner/answer_rewrite/answer generation LLM wrapper | 调整默认模型配置；部署或本机差异优先放 `.env` |

## `llm.yaml` 和 `.env` 的关系

`llm.yaml` 是 QA graph 的默认 LLM 配置；`.env` 是运行时覆盖层。

常见对应关系：

| `.env` | 覆盖/补充 | 说明 |
| --- | --- | --- |
| `RESUME_QA_LLM_PROVIDER` | `llm.yaml.provider` | QA graph 使用 OpenAI、Ollama 或其他 provider |
| `RESUME_QA_OPENAI_MODEL` | `llm.yaml.openai_model` | QA 侧 OpenAI 模型 |
| `RESUME_QA_OLLAMA_MODEL` | `llm.yaml.ollama_model` | QA 侧 Ollama 模型 |
| `RESUME_QA_OLLAMA_BASE_URL` | `llm.yaml.ollama_base_url` | QA 侧 Ollama 地址 |
| `OPENAI_API_KEY` | 不属于 YAML | 真实密钥，只放 `.env` 或 secret storage |

如果配置是“这个环境怎么连模型”，优先看 `.env`。如果配置是“系统默认用什么模型参数”，再看 `llm.yaml`。

## Compiler 开关

当前只暴露一个公开开关：

```env
RESUME_QA_WORKFLOW_TEMPLATE_COMPILER_ENABLED=true
```

语义：

```text
true
-> hybrid_template_binding
-> 稳定 workflow/template 优先，未命中时 generic fallback

false 或未配置
-> generic_tool_binding
-> 直接走 planner + generic tool binding
```

旧的 generic 单独开关和手动 mode 开关不再作为公开运行配置。内部 trace 仍然会展示 `hybrid_template_binding` / `generic_tool_binding`，但运行配置只看 workflow 开关。

## 怎么判断该改哪个 YAML

| 目标 | 首选位置 |
| --- | --- |
| 新增用户意图 | `intents.yaml`，再同步 schema/router/compiler/validator |
| 新增或调整执行场景 | `scenarios.yaml` |
| 调整 router 规则兜底或越界判断 | `router_rules.yaml` |
| 调整条件抽取、alias 或 taxonomy 映射 | `condition_rules.yaml` + `shared_taxonomy/` |
| 沉淀稳定工具链 | `compiler_templates.yaml` |
| 新工具上线或调整工具权限 | `tool_policy.yaml` |
| 调整 repair / retry / validator 动作 | `validation.yaml` |
| 调整答案结构和 section | `answer_layouts.yaml` |
| 调整答案任务分类 | `aggregator_tasks.yaml` |
| 调整证据要求 | `evidence_policy.yaml` |
| 调整排序评分口径 | `jd_scoring.yaml` |
| 调整 QA LLM 默认 provider/model | `llm.yaml` |

## 和 Python 层的边界

`configs/`：

- 保存规则和合同。
- 不关心调用顺序。
- 不知道哪个 node 当前在执行。

`core/config/`：

- 读取 YAML。
- 构造 `ResumeQAConfig`。
- 提供查询方法，隐藏 YAML shape。
- 加载 `.env` 中的运行开关。

`core/config_validation/`：

- 启动期检查跨 YAML 引用。
- 有错直接抛 `ConfigStructureError`。
- 不修复配置。

## 阅读顺序

1. [README.md](README.md)
2. [../core/config/README.md](../core/config/README.md)
3. [../core/config/CONFIG_FLOW.md](../core/config/CONFIG_FLOW.md)
4. [../core/config_validation/README.md](../core/config_validation/README.md)
5. [../core/config_validation/VALIDATION_FLOW.md](../core/config_validation/VALIDATION_FLOW.md)

## 维护原则

- 能放 YAML 的稳定规则，不散落到 node 代码里。
- 能通过 `ResumeQAConfig` 查询的配置，不让节点直接解析 YAML shape。
- 涉及密钥、本机地址、部署差异的内容，放 `.env` 或部署 secret。
- 涉及跨 YAML 引用的改动，要同步跑 config validation。
