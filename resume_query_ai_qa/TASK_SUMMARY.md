# Resume Query AI QA Task Summary

本文档记录当前 `resume_query_ai_qa` 任务进度：已经完成什么、还剩什么、下一步优先做什么。

## P0 工业级问答闭环状态

已按 P0 目标完成后端 API + 前端 AI 问答入口闭环：

- 后端新增 `POST /qa/ask`，由 `resume_query_api.routes.qa` 调用 `resume_query_ai_qa.graph.run()`，并返回前端稳定消费的 `status/answer/claims/evidence/ranking/session_context/trace`。
- 前端 `resume_query_frontend_v3` 左侧导航新增“AI 问答”，右侧采用单页双栏目：主区域问答历史和输入，信息区域展示排序、评分、证据、claims、trace 摘要。
- 页面内保存并回传 `updated_session_context`，支持“他/她/第一名/这两个人”等多轮 follow-up；刷新页面不持久化会话。
- `needs_clarification` 作为正常业务状态返回，前端显示追问文本和候选项；点击候选项会结合上一轮问题继续发送。
- 前端不重新计算排序，不改变后端 `rank_candidates` 顺序；联系方式和敏感字段仍沿用 QA 工具/validator 的默认隐藏边界。
- 新增 `hybrid_search_candidates` 语义召回工具，用于“谁有某类经验/背景/能力”这类问题：SQL/tag/work/project 结构化召回 + bge-m3 向量召回 + deterministic rerank；它只回答“谁相关”，不替代 JD scoring 排序。

当前 P0 验证命令：

```bash
./.venv/bin/python -m compileall -q resume_query_ai_qa resume_query_api
rg "resume_query_v3|rewrite_v1|resume_query_api|core.data_layer|invoke_llm|get_config" resume_query_ai_qa -g '*.py'
PATH=/Users/supernoodle/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:$PATH npm run build
```

API smoke 已通过：

```bash
./.venv/bin/python -m uvicorn resume_query_api.main:app --host 127.0.0.1 --port 8002
curl -s -X POST http://127.0.0.1:8002/qa/ask \
  -H 'Content-Type: application/json' \
  -d '{"question":"有多少个金融领域候选人，都有谁？","use_llm":false}'
```

注意：当前本机 `127.0.0.1:8000` 可能已有旧后端进程占用；如果前端要访问新 `/qa/ask`，需要重启 8000 后端，或设置 `NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8002` 指向新服务。

## 当前目标

新增一条基于 v3 数据底座的简历 AI 问答链路，用于回答招聘侧自然语言问题，例如：

- 有多少个候选人？
- 有多少个金融领域候选人，都有谁？
- 介绍某人的个人信息。
- 某人的项目证据在哪里？
- 多个候选人谁更好，按 JD 做排序。

核心方向：

```text
router
-> planner
-> plan_validator
-> executor
-> execution_validator
-> aggregator
-> answer_validator
```

当前实现是 **LangGraph StateGraph + LLM + deterministic fallback 闭环**。

当前可稳定问答的入口是 **rule fallback**：

- 使用 `--no-llm`。
- 或设置 `RESUME_QA_LLM_PROVIDER=disabled`。

LLM 链路代码已经接入 router/planner/aggregator，但稳定性取决于实际 provider 是否可用。当前 `configs/llm.yaml` 默认是 `provider: "openai"`，并读取根目录 `.env` 中的 `OPENAI_API_KEY`；rule fallback 仍可用作稳定检查入口。

## 已完成

### 1. 新建 QA 包结构

已新增目录：

```text
resume_query_ai_qa/
  README.md
  TASK_SUMMARY.md
  __init__.py
  core/
  graph/
  nodes/
  tools/
  scoring/
  evidence/
  configs/
  scripts/
  tests/
```

prompt 已集中到 `core/llm/prompts.py`，根目录保持干净，只保留 README、任务总结和包入口。

### 2. 架构 README

已写入：

- 责任边界
- 禁止事项
- 补充边界
- LangGraph 主链
- 回退与修复规则
- 问题分类
- tool 白名单
- YAML 驱动
- JD 评分细则
- 比较与排序边界
- 工程框架
- 节点输入输出契约
- 观测与日志边界
- 测试边界
- 发展路线

文件：

```text
resume_query_ai_qa/README.md
```

### 3. YAML 策略配置

已新增：

```text
resume_query_ai_qa/configs/intents.yaml
resume_query_ai_qa/configs/tool_policy.yaml
resume_query_ai_qa/configs/jd_scoring.yaml
resume_query_ai_qa/configs/evidence_policy.yaml
resume_query_ai_qa/configs/validation.yaml
resume_query_ai_qa/configs/llm.yaml
```

这些配置目前覆盖：

- intent 分类
- intent 到 tool 的允许关系
- JD scoring 权重
- evidence policy
- compare/ranking/answer validation 规则
- 隐私与敏感属性边界
- QA 自有 LLM provider/model/timeout 配置

### 4. Pydantic 契约

已新增：

```text
resume_query_ai_qa/core/schemas.py
```

包含：

- `IntentName`
- `EvidenceRef`
- `CandidateBrief`
- `JDScoringCriteria`
- `CandidateScore`
- `ToolCallSpec`
- `SubTaskPlan`
- `QueryPlan`
- `RouterOutput`
- `ValidationResult`
- `ToolResult`
- `AggregatedAnswer`
- `ResumeQAState`
- `ResumeQATrace`

### 5. 配置加载器

已新增：

```text
resume_query_ai_qa/core/config.py
```

支持：

- 读取全部 YAML。
- 查询某个 intent 的 allowed tools。
- 查询 retry limit。

### 6. 确定性 tools

已实现：

```text
resume_query_ai_qa/tools/registry.py
```

包括：

- `list_all_candidates`
- `filter_candidates`
- `count_candidates`
- `get_candidate_brief`
- `get_candidate_profile_intro`
- `get_candidate_evidence`
- `search_candidate_evidence`
- `hybrid_search_candidates`
- `resolve_candidate_reference`
- `build_comparison_pack`
- `get_tool_registry`

工具边界：

- 只读。
- 不调用 LLM。
- 不生成最终答案。
- 不做主观排序。
- `hybrid_search_candidates` 只做召回和相关度解释，不做“谁更好”的排序；“谁更好/排名”仍必须走 `score_candidates_for_jd` + `rank_candidates`。
- 默认隐藏联系方式。

`hybrid_search_candidates` 返回结构：

- `resume_identity/name`
- `score/structured_score/evidence_score/work_score`
- `match_reasons`
- `match_channels`
- `brief`
- `work_experiences`
- `projects`
- `evidence_refs`

典型验证：

```bash
./.venv/bin/python -m resume_query_ai_qa.scripts.run_qa '谁有计算机相关经验？' --no-llm --show-trace
./.venv/bin/python -m resume_query_ai_qa.scripts.run_qa '有多少个候选人有计算机相关经验，都有谁？' --no-llm --answer-only
```

### 7. JD 评分工具

已实现：

```text
resume_query_ai_qa/scoring/jd.py
```

包括：

- `load_default_jd_criteria`
- `extract_jd_criteria`
- `score_candidate_for_jd`
- `score_candidates_for_jd`
- `rank_candidates`

当前评分是规则版，基于：

- domain match
- required skill match
- project evidence
- work experience
- communication/language
- risk penalty

### 8. 节点与边界校验

已实现：

```text
resume_query_ai_qa/nodes/router.py
resume_query_ai_qa/nodes/planner.py
resume_query_ai_qa/nodes/executor.py
resume_query_ai_qa/nodes/plan_validator/
resume_query_ai_qa/nodes/execution_validator/
resume_query_ai_qa/nodes/answer_validator/
resume_query_ai_qa/nodes/aggregator.py
```

当前是 LLM + rule-fallback 版本：

- `router.py`：LLM 分类，失败回退规则分类。
- `planner.py`：LLM 生成 plan，失败或不合法回退规则 plan。
- `executor.py`：按 plan 调用工具。
- `nodes/plan_validator/`、`nodes/execution_validator/`、`nodes/answer_validator/`：plan/execution/answer 校验，覆盖 tool 白名单、工具参数、count/name/rank/evidence/contact。
- `aggregator.py`：LLM 生成答案，失败或不合法回退规则答案。

已增强：

- `count`：plan 必须有候选人来源和 `count_candidates`；执行结果会校验 count 与候选人源数量一致。
- `name`：显式 name claim 必须来自 tool results。
- `rank`：答案排序段落必须与 `rank_candidates` 输出顺序一致。
- `evidence`：按 YAML evidence policy 检查最小证据覆盖。
- `contact`：默认禁止 email/phone/wechat 泄露，除非工具明确返回可展示 contact。
- `tool args`：validator 会用工具签名拦截 LLM 生成的非法参数。
- `bilingual`：router/planner/tool alias 同时支持中文和英文触发词；人名支持中文原名、英文/拼音 alias。

### 8.1 自有 LLM 层

已实现：

```text
resume_query_ai_qa/core/llm/client.py
```

特点：

- 使用 `ChatOpenAI` / `ChatOllama`。
- 使用 LangChain `with_structured_output(method="function_calling")`。
- 会加载项目根目录 `.env`，但只读取环境变量，不 import v3 配置。
- 只读取 `resume_query_ai_qa/configs/llm.yaml`、`RESUME_QA_*` 环境变量，以及通用 `OPENAI_API_KEY`。
- 不引用 v3 LLM/config/prompt。

### 9. Runner 和 CLI

已实现：

```text
resume_query_ai_qa/graph/runner.py
resume_query_ai_qa/scripts/run_qa.py
```

当前 runner 已改为正式 LangGraph `StateGraph`，节点和 conditional edges 为：

```text
router
-> planner
-> plan_validator
   -> invalid: plan_repair
-> executor
-> execution_validator
   -> invalid: execution_repair
-> aggregator
-> answer_validator
   -> invalid: answer_rewrite / rule_answer_fallback
-> final / fail
```

特点：

- 使用 `START` / `END`。
- plan validation 失败会先尝试 LLM repair，次数用尽后走 deterministic rule plan。
- execution validation 失败会回到 rule plan 修复。
- answer validation 失败会先 rewrite，再走 rule aggregator fallback。

CLI 支持：

```bash
./.venv/bin/python -m resume_query_ai_qa.scripts.run_qa '有多少个候选人？'
./.venv/bin/python -m resume_query_ai_qa.scripts.run_qa '有多少个候选人？' --answer-only
./.venv/bin/python -m resume_query_ai_qa.scripts.run_qa '有多少个候选人？' --no-llm --answer-only
```

### 9.1 当前可稳定运行方式

Ollama 未启动时，推荐用下面两种稳定入口：

```bash
./.venv/bin/python -m resume_query_ai_qa.scripts.run_qa '有多少个金融领域候选人，都有谁？' --no-llm --answer-only
RESUME_QA_LLM_PROVIDER=disabled ./.venv/bin/python -m resume_query_ai_qa.scripts.run_qa '介绍一下孟连星的个人信息' --answer-only
./.venv/bin/python -m resume_query_ai_qa.scripts.run_qa '有多少个候选人，都有谁，谁更好，做个排序' --no-llm --answer-only
```

如果要走 Chat/OpenAI，而不是 Ollama：

```bash
RESUME_QA_LLM_PROVIDER=openai OPENAI_API_KEY='你的 key' ./.venv/bin/python -m resume_query_ai_qa.scripts.run_qa '有多少个金融领域候选人，都有谁？' --answer-only --show-trace
```

也支持 QA 自有 key 名：

```bash
RESUME_QA_LLM_PROVIDER=openai RESUME_QA_OPENAI_API_KEY='你的 key' ./.venv/bin/python -m resume_query_ai_qa.scripts.run_qa '介绍一下孟连星的个人信息' --answer-only --show-trace
```

注意：OpenAI/Chat 路径代码已接，但还没有在当前环境完成稳定回归。正式判断稳定前，需要跑完本文档“已验证”里的 LLM path regression。

## 已验证

已跑通过的稳定路径是 rule fallback：

```bash
./.venv/bin/python -m resume_query_ai_qa.scripts.run_qa '有多少个金融领域候选人，都有谁？' --no-llm --answer-only
RESUME_QA_LLM_PROVIDER=disabled ./.venv/bin/python -m resume_query_ai_qa.scripts.run_qa '介绍一下孟连星的个人信息' --answer-only
./.venv/bin/python -m resume_query_ai_qa.scripts.run_qa '有多少个候选人，都有谁，谁更好，做个排序' --no-llm --answer-only
./.venv/bin/python -m compileall -q resume_query_ai_qa
```

已跑通过边界扫描：

```bash
rg "resume_query_v3|rewrite_v1|resume_query_api|core.data_layer|invoke_llm|get_config" resume_query_ai_qa -g '*.py'
```

结果：无 Python 代码引用 v3 内部实现。

当前本地数据结果：

- 候选人总数：4 位。
- 金融领域候选人：孟连星。
- 个人介绍默认隐藏联系方式。
- 多人排序基于默认 `JD.md` 规则评分。

### Chat/OpenAI 当前验证结果

已接通根目录 `.env` 中的 `OPENAI_API_KEY`，并用 OpenAI provider 跑通核心问题：

```bash
RESUME_QA_LLM_PROVIDER=openai ./.venv/bin/python -m resume_query_ai_qa.scripts.run_qa '有多少个金融领域候选人，都有谁？' --answer-only --show-trace
RESUME_QA_LLM_PROVIDER=openai ./.venv/bin/python -m resume_query_ai_qa.scripts.run_qa '介绍一下孟连星的个人信息' --answer-only --show-trace
RESUME_QA_LLM_PROVIDER=openai ./.venv/bin/python -m resume_query_ai_qa.scripts.run_qa '有多少个候选人，都有谁，谁更好，做个排序' --answer-only --show-trace
RESUME_QA_LLM_PROVIDER=openai ./.venv/bin/python -m resume_query_ai_qa.scripts.run_qa '孟连星和孔德程谁更好？' --answer-only --show-trace
```

结果：

- 三条最终 `final_status` 都是 `ok`。
- 三条 `router_output.risk_flags` 都为空，没有 `llm_*_fallback`。
- router / planner / aggregator 已走 Chat/OpenAI。
- rule fallback 仍可用，作为 provider 失败时的兜底。

验证中发现并已修复：

- OpenAI structured output 默认 `json_schema` 会提示 schema warning，已改为 `method="function_calling"`。
- LLM planner 可能把 `Finance` 写成中文“金融”，工具层已做 domain alias 归一。
- LLM planner 可能生成空参数 `count_candidates`，executor 已把它绑定到上一轮候选人列表结果，避免筛选后计数变成全量计数。

当前 OpenAI path 已验证的事实结果：

- 金融领域候选人：1 位，孟连星。
- 个人介绍：孟连星，可生成自然语言介绍，联系方式默认隐藏。
- 排序问题：4 位候选人，按默认 JD 规则评分排序，孔德程第一、孟连星第二、张英杰第三、DavidMeng 第四。
- 双人比较：孟连星 vs 孔德程，只比较两人，基于 comparison pack 和项目证据输出。

### Evidence policy 当前状态

已实现：

```text
resume_query_ai_qa/evidence/policy.py
```

包含：

- `required_evidence_policy`
- `collect_evidence_refs`
- `available_evidence_ids`
- `validate_evidence_coverage`
- `candidate_ids_requiring_evidence`

当前由 `configs/evidence_policy.yaml` 驱动：

- 每个 intent 是否需要 evidence。
- 每个候选人最小 evidence 数量。
- 弱证据 warning。
- answer 使用的 evidence id 必须来自 tool results。

### 双人 compare 当前状态

已完成：

- router 识别明确双人比较。
- planner 使用 `resolve_candidate_reference` + `build_comparison_pack`。
- validator 限制 compare 必须正好 2 人。
- executor 调用 comparison pack。
- aggregator 输出双方事实、证据和倾向结论。
- 三人以上或要求排序时仍走 ranking，不走 compare。

### 中英文兼容当前状态

已完成：

- router 规则同时识别中文和英文 intent：
  - count：`多少/几个/总数`、`how many/count/number of/total`
  - list：`都有谁/有哪些/名单/列出`、`who/list/names/which candidates`
  - profile：`介绍/个人信息/背景`、`introduce/profile/personal info/background/tell me about`
  - evidence：`证据/体现在哪里/项目里`、`evidence/proof/project evidence`
  - ranking：`排序/排名/谁更好/推荐`、`rank/ranking/better/stronger/recommend`
  - compare：`比较/对比/谁更好`、`compare/vs/versus/better`
- planner fallback 同时识别中文和英文过滤条件：
  - `金融/finance/financial/fintech/banking` -> `Finance`
  - `推荐系统/recommendation/recommender`
  - `搜索/search`
  - `python/rag`
- tools 层做 domain alias 归一，不依赖 LLM：
  - `金融/financial/fintech/banking` -> `Finance`
  - `AI Search/搜索/search` -> `AI Search`
- candidate resolver 支持中文姓名和常见英文/拼音 alias：
  - `孟连星` / `Meng Lianxing`
  - `孔德程` / `Kong Decheng`
  - `张英杰` / `Zhang Yingjie`
  - `DavidMeng` / `David Meng`

已验证英文 rule fallback：

```bash
./.venv/bin/python -m resume_query_ai_qa.scripts.run_qa 'How many finance candidates are there, and who are they?' --no-llm --answer-only
./.venv/bin/python -m resume_query_ai_qa.scripts.run_qa 'Tell me about Meng Lianxing profile' --no-llm --answer-only
./.venv/bin/python -m resume_query_ai_qa.scripts.run_qa 'Compare Meng Lianxing and Kong Decheng, who is better?' --no-llm --answer-only
./.venv/bin/python -m resume_query_ai_qa.scripts.run_qa 'How many candidates are there, who are they, and rank them' --no-llm --answer-only
```

保证方式：

- 第一层靠 deterministic bilingual rules，不靠 LLM；所以 `--no-llm` 也支持中英文。
- 第二层靠 LLM router/planner 理解自然语言；如果 LLM 失败或输出非法参数，validator 会拦截并回退 rule plan。
- 第三层靠 tools/validators 做事实和边界校验；语言不同不会改变 count/rank/evidence/contact 的事实来源。

## 尚未完成

### 1. LLM provider 稳定性还需要继续加固

当前 LLM 接入代码已完成，但环境状态是：

- `configs/llm.yaml` 默认 provider 是 `openai`。
- OpenAI/Chat 路径已接通，当前环境通过根目录 `.env` 的 `OPENAI_API_KEY` 可跑通 regression。
- bge-m3 向量召回仍依赖本机 Ollama embedding；未启动时 `hybrid_search_candidates` 会降级到 SQL/tag/work/project 召回。

还需要：

- 补充 provider 自动化回归，覆盖 OpenAI 成功、provider 失败 fallback、bge-m3 不可用降级。
- 为 OpenAI path 补自动化 regression tests。
- 把 `--show-trace` 中 executor 实际绑定后的 tool arguments 也记录出来，便于观察 count repair。
- 继续记录 LLM 失败时是否按预期回退 rule path。

### 2. LLM 节点还需要继续增强

当前已接 LLM router/planner/aggregator，并保留规则 fallback。

还需要：

- 更强的 prompts。
- LLM planner 不依赖规则 planner 预填参数。
- LLM aggregator 输出更稳定的 claims/evidence refs。

### 3. Validator 还需要继续增强

已补强 count/name/rank/evidence/contact/tool args。还需要：

- 检查敏感属性没有进入判断。
- 增加更细的 claim parser，减少依赖 LLM 自填 claims。
- 把更多工具参数 alias 放入 plan repair 或参数归一化层。

### 4. JD scoring 仍然是粗规则版

还需要：

- 更细的 JD criteria 抽取。
- 更稳定的 skill/domain taxonomy 对齐。
- 证据覆盖率计入评分。
- 风险扣分更精细。
- 输出评分解释表。

### 5. 多轮 follow-up 还很粗

已有：

- `resolve_candidate_reference`

还缺：

- session context 结构设计。
- 最近一次 ranking / comparison / focused candidate 的写入。
- follow-up 自动转具体 intent。
- 歧义澄清。

### 6. API 还没接入

还未新增：

```text
POST /qa/ask
```

需要在 `resume_query_api` 中新增路由，调用：

```python
resume_query_ai_qa.graph.run()
```

### 7. 前端还没接入

还没在 v3 前端新增问答入口。

后续需要：

- 问答输入框。
- 答案展示。
- 排序表。
- 证据展示。
- trace/debug 摘要。

### 8. 测试还没写

目前只有 tests 目录占位。

需要新增：

- schema tests
- tool tests
- validator tests
- scoring tests
- graph case tests
- regression tests

## 下一步建议

推荐顺序：

1. **写自动化测试**
   - 覆盖 rule path、OpenAI path fallback、compare、ranking、contact 泄露拦截。

2. **增强 LLM planner 参数规范**
   - 把 `industry`、`keyword` 等常见错误参数统一 repair/normalize。

3. **增强 LLM aggregator claims**
   - 要求 count/name/rank/evidence claims 更稳定，减少 rule fallback。

4. **接 API**
   - 新增 `/qa/ask`。

5. **接前端**
   - 接问答入口、证据、排序表、trace 摘要。

## 当前风险

- `configs/llm.yaml` 默认是 `provider: "openai"`；如果 OpenAI 不可用会走 rule fallback。稳定检查仍可用 `--no-llm` 或 `RESUME_QA_LLM_PROVIDER=disabled`。
- OpenAI/Chat 路径已接通并跑通核心问题，但仍需要自动化测试才能宣称产品级稳定。
- 当前 planner 为了让 rule-fallback 可跑，会在规划阶段预先调用部分 deterministic tools 准备参数；正式 LLM planner 接入后，应改成“planner 只规划，executor 串联工具结果”。
- 当前 LLM planner 仍可能输出不理想参数；validator 会拦截并触发 repair/fallback，但还需要更多参数归一化减少失败重试。
- 当前答案仍偏规则模板，不是最终自然语言体验。
- 当前 JD scoring 是粗规则版，适合作为 baseline，不适合作为最终招聘评分。
- 当前 CLI 默认可输出完整 state，里面可能包含较多简历内容；对外产品化时需要做脱敏和摘要。
