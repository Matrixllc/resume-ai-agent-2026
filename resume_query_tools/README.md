# resume_query_tools

`resume_query_tools` 是事实读取层。它把 SQLite 和 Chroma 中的简历数据包装成只读
Python API，供 `resume_query_ai_qa` 和 `resume_query_api` 使用。

它不规划问题、不生成答案、不调用 LLM、不写库。

## 责任边界

| 负责 | 不负责 |
|---|---|
| 读取结构化候选人信息。 | 判断用户 intent。 |
| 读取项目级 evidence chunks。 | 生成 `QueryPlan`。 |
| 返回稳定 DTO。 | 总结、排序解释、自然语言回答。 |
| 提供候选人展示和检索事实。 | 写 SQLite/Chroma。 |

## 数据来源

默认路径：

```text
SQL:    resume_query_v3/data/structured/structured_store.db
Chroma: resume_query_v3/data/vector/chroma_store
```

可用环境变量覆盖：

```text
RESUME_TOOLS_SQLITE
RESUME_TOOLS_CHROMA_DIR
RESUME_TOOLS_CHROMA_COLLECTION
```

## 在主链中的位置

```text
resume_query_v3 -> SQLite/Chroma -> resume_query_tools -> resume_query_ai_qa
```

Query-AI 只能通过注册工具读取事实。任何答案中的人数、名单、排序、证据都必须能追溯到
tools 的返回结果。

## 使用方式

API 层用于候选人展示：

```text
GET /candidates
GET /candidates/{resume_identity}
GET /candidates/{resume_identity}/projects
```

Query-AI 层通过内部 registry 调用工具：

```text
filter_candidates
hybrid_search_candidates
resolve_candidate_reference
get_candidate_profiles_intro
search_candidate_evidence
score_candidates_for_jd
rank_candidates
build_comparison_pack
```

## 扩展原则

新增工具时必须满足：

1. 只读。
2. 返回结构化 DTO 或可被 Pydantic 校验的数据。
3. 注册到 Query-AI tool registry。
4. 更新 `tool_policy.yaml`。
5. 补 compiler/validator/answer benchmark。

## 检查

```bash
.venv/bin/python -m compileall -q resume_query_tools
```
