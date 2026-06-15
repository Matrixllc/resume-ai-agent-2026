# resume_query_v3 Flow

这份文档只解释 `resume_query_v3` 的入库 flow。它的定位是数据基座：先把简历数据做准、做稳、做可追溯，再给 `resume_query_tools` 和 `resume_query_ai_qa` 使用。

主链路：

```text
parse_resume
-> build_rule_candidates
-> resolve_with_llm_or_rule_fallback
-> validate_payload
-> apply_storage_gate
-> write_storage_and_artifacts
```

## 1. parse_resume

输入：本地简历文件路径和 v3 config。

做什么：把 PDF、DOCX 或文本简历解析成 `DocumentBlock` 列表，每个 block 保留 `block_id`、页码、文本和来源文件。这个 node 的核心价值是把不可控的文件输入变成后面每一步都能引用的证据块。

不做什么：不判断候选人能力，不生成问答计划，不写数据库。

输出：`DocumentBlock[]` 和 parser diagnostics，例如 `parser_mode`、`parser_fallback_reason`。

## 2. build_rule_candidates

输入：`DocumentBlock[]`、section aliases、routing/chunking config、taxonomy/domain config。

做什么：用规则先做第一轮数据收口，包括文档画像、候选人基础字段、工作经历、教育经历、技能/领域标签、项目候选块和项目边界质量诊断。

不做什么：不把规则结果直接当作最终真相，也不直接写入 SQLite/Chroma。

输出：rule payload，包括 `candidate_profile`、`work_experiences`、`education_experiences`、`concept_tags`、`domain_tags`、`project_candidate_groups`、`project_boundary_quality`。

## 3. resolve_with_llm_or_rule_fallback

输入：rule payload 和 LLM config。

做什么：用 LLM 对项目边界做校验或修复。如果规则判断项目边界需要修复，就走 project repair prompt；否则走 boundary check prompt。LLM 成功时，把选择后的项目、字段和证据合并回统一 payload。

不做什么：不直接落库，不绕过 validation，也不承担问答回答职责。

输出：llm payload、`resolve_mode`、`llm_prompt`、`raw_response`。如果 LLM 不可用或返回异常，输出 rule fallback payload，并把 `resolve_mode` 标记为 `rule_fallback`。

## 4. validate_payload

输入：合并后的 ingestion payload、validate config、允许的 concepts/domains。

做什么：检查字段置信度、标签 taxonomy、chunk evidence 等基本质量要求。通过的内容继续向后走，不够稳的内容进入 `needs_review` 或被拒绝。

不做什么：不重新生成字段，不修复问答策略，不做向量写入。

输出：validated payload 和 `validation_summary`。

## 5. apply_storage_gate

输入：validated payload。

做什么：决定项目数据是否可以进入长期存储。这里重点保护“项目边界准确性”：LLM 成功或修复成功时正常放行；LLM 不可用时，只有可信的 rule grouping 才能放行；低质量项目边界会被拦截。

不做什么：不生成 embedding，不写 SQL，不改变候选人基础字段。

输出：storage-ready payload、`storage_gate`、`project_count_for_storage`。如果项目边界不可信，`projects` 和 `project_chunks` 会被清空，避免污染数据底座。

## 6. write_storage_and_artifacts

输入：storage-ready payload、structured/vector backend config、prompt/response。

做什么：把结构化数据写入 SQLite，把项目证据写入 Chroma 或 JSON fallback，同时生成 `storage_summary`。最后写 latest/history 运行产物，方便回看这次入库用了什么 prompt、LLM 返回了什么、最后写入了哪些行。

不做什么：不重新判定项目可信度，不改变 validation 结果，不直接服务前端展示。

输出：最终 ingestion result，包括 `run_meta`、`storage_gate`、`storage_summary` 和 latest/history artifact。

## 这条链路如何支撑问答

v3 写出的数据不是直接给前端消费，而是按下面的方向流动：

```text
resume_query_v3
-> SQLite / Chroma
-> resume_query_tools
-> resume_query_ai_qa
-> resume_query_api / resume_query_frontend_v3
```

SQLite 负责候选人、经历、标签、项目 manifest 等结构化事实。Chroma 负责项目级证据召回。`resume_query_tools` 只读这些存储，把它们包装成 QA graph 可以调用的工具。这样 QA graph 只需要负责理解问题、选择工具和组织答案，不需要重新承担入库和数据清洗责任。

## 失败和降级也要保证数据准确

这条链路不是“任何结果都写进去”，而是“能证明可信才写进去”。

- Docling 不可用时，可以退回 builtin parser。
- LLM 不可用时，可以退回 rule fallback。
- 项目边界不可信时，storage gate 会拦截项目数据。
- Chroma 不可用时，可以退回 JSON vector payload，不影响 SQLite 结构化事实写入。
- 每次运行都会保留 latest/history artifact，方便定位是哪一步导致数据变化。

这就是 v3 的核心取舍：演示系统可以轻，但数据底座不能乱。只要数据先准确、证据能追溯，后面的问答链路才有可靠的基础。
