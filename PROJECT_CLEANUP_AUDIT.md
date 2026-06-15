# 项目清理与代码质量审计报告

日期：2026-06-16

## 总结

本报告记录统一运行数据目录到根目录 `data/` 之后的项目收尾检查。

结论：
- 已删除旧运行入口：根目录 `resume/`、`vector_db/`、`resume_query_v3/data/`、`resume_query_v3/resume/`。
- 已清理可再生成的本地文件：`__pycache__/`、`.DS_Store`、QA 日志、前端 `.next*` 构建输出、`data/backups/`。
- 已保留当前运行所需内容：`.env`、`.venv/`、`resume_query_frontend_v3/node_modules/`、`data/resume/`、`data/structured/`、`data/vector/`。

## 清理结果

部署前必须修复：
- 未发现旧数据路径阻断项。静态搜索未发现生产代码继续引用 `vector_db`、`resume_query_v3/data` 或 `repo_root / "resume"`。

可以保留：
- `data/resume/` 中是当前本地简历输入和上传文件，属于运行数据，已被 `.gitignore` 忽略；源码只应保留 `data/resume/.gitkeep`。
- `.env`、`.venv/`、`node_modules/` 是本地环境和依赖状态，本次按计划不删除。

部署提醒：
- `data/structured/` 下的 SQLite 和 `data/vector/` 下的 Chroma 都是运行状态，不应该提交到 Git。

## 代码质量结论

部署前必须修复：
- 本轮审计未发现阻断部署的架构问题。

可以部署后优化：
- `resume_query_v3/core/data_layer/runtime/rule_matcher.py` 约 2400 行，是当前最大的 Python 规则集中区。它不是简单编排文件，后续最适合拆分或配置化。
- `resume_query_api/qa_trace.py` 和 `resume_query_v3/core/data_layer/llm/checker.py` 接近 1000 行，职责还算集中，但不建议继续膨胀。
- `resume_query_api/routes/ingestion.py` 约 500 行，混合了 API、reset、上传路径校验和批量任务汇报。当前可保留，后续可拆 helper。

可以保留：
- `resume_query_ai_qa` 整体已经比较规则/配置驱动，核心配置集中在 `resume_query_ai_qa/configs/`。
- `resume_query_v3` 的 chunking、routing、section aliases、validate 等规则集中在 `resume_query_v3/configs/`。
- 共享领域词表在 `shared_taxonomy/`。
- 若干 `compat` / facade 模块是为了保持旧导入路径稳定，当前不是部署阻断项。

## 超长 Python 文件

超过 500 行的文件：

| 行数 | 文件 | 判断 |
| ---: | --- | --- |
| 2403 | `resume_query_v3/core/data_layer/runtime/rule_matcher.py` | 最大的硬编码规则集中区，后续优先拆分。 |
| 965 | `resume_query_api/qa_trace.py` | trace / 渲染支持逻辑较大，当前可保留。 |
| 928 | `resume_query_v3/core/data_layer/llm/checker.py` | LLM 检查流程较大，当前可保留。 |
| 552 | `resume_query_ai_qa/scoring/jd.py` | JD 评分逻辑较集中，不建议再混入无关逻辑。 |
| 512 | `resume_query_api/routes/ingestion.py` | API 路由和批量/reset 编排混在一起，后续可抽取。 |

300 到 500 行之间的文件主要包括 storage、schemas、router rules、guards、pipeline、prompts、plan builders 和 tool 实现。只要测试通过，当前收尾阶段可以接受。

## 规则驱动与边界判断

总体判断：
- QA 和 taxonomy 层已经基本规则/配置驱动。
- 入库层仍有明显 Python 内嵌规则和正则，集中在 `rule_matcher.py`。
- 服务边界整体清楚：API 负责路由和任务编排，v3 负责入库和存储，tools 只读统一数据源，ai_qa 负责规划、执行和答案生成。

后续建议：
- 将 `rule_matcher.py` 拆成更小的领域文件，或把稳定模式表迁到 YAML。
- 如果 `resume_query_api/routes/ingestion.py` 继续增长，优先抽出 reset、upload、batch job helper。
- 兼容 wrapper 只保留仍被 benchmark 或外部导入路径依赖的部分。

## 验证命令

最终部署前建议再跑：

```bash
./.venv/bin/python -m compileall -q resume_query_api resume_query_v3 resume_query_ai_qa resume_query_tools resume_query_common
rg -n 'vector_db|resume_query_v3/data|repo_root / "resume"|Path\("resume"\)|directory or "resume"' --glob '*.py' --glob '*.md' --glob '*.env*' --glob '!data/**'
git status --short --ignored
```
