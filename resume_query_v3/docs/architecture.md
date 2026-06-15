# Resume Query V3 Architecture

`resume_query_v3` 是 Query-AI 的数据基座，不是问答主链。它的核心职责是把简历文件转成可信数据：字段要准确，项目边界要可解释，证据要能追溯，存储前要能被校验。

## 主链

```text
parse_resume
-> build_rule_candidates
-> resolve_with_llm_or_rule_fallback
-> validate_payload
-> apply_storage_gate
-> write_storage_and_artifacts
```

## Node 边界

| Node | 只负责 | 不负责 |
|---|---|---|
| `parse_resume` | 文件解析、文本块生成、parser 诊断。 | 判断简历语义、写存储。 |
| `build_rule_candidates` | 规则抽取、文档画像、区块压缩、项目候选和边界诊断。 | 最终认定项目边界。 |
| `resolve_with_llm_or_rule_fallback` | LLM 校验/修复项目边界；异常时生成 rule fallback。 | 直接修改数据库。 |
| `validate_payload` | confidence、taxonomy、evidence 校验。 | 决定问答策略。 |
| `apply_storage_gate` | 项目事实入库准入、项目/项目块去重。 | 生成 embedding 或 SQL 行。 |
| `write_storage_and_artifacts` | 写 SQLite、写 Chroma、写 latest/history 审计产物。 | 变更入库事实判断。 |

## 模块归位

- `pipeline.py`：公开入口和 node 编排层，只串链路、记录 progress、更新 job 状态。
- `runtime/rule_matcher.py`：规则侧数据候选生成。
- `runtime/validator.py`：入库 payload 校验。
- `runtime/storage_quality.py`：storage gate 和项目事实去重。
- `runtime/storage_summary.py`：把准备写入的 SQL/Chroma 数据整理成可读摘要。
- `runtime/run_artifacts.py`：写 latest/history prompt、response、run json 和 run log。
- `storage/`：SQLite、Chroma、JSON fallback 的具体读写实现。

## 数据准确性原则

- v3 产物必须能从 storage row 回到 `resume_identity`、source path、evidence block。
- LLM 输出只作为候选事实来源，必须经过 validation 和 storage gate。
- 项目级数据宁可被 gate 拦下，也不要把低可信项目边界写入长期存储。
- Query-AI 主链只能通过 tools/API 读取 v3 数据，不直接 import 入库 pipeline。
