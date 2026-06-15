# Scripts Package

`scripts` 是 Query-AI 的本地 CLI / 调试入口包。

一句话：

```text
scripts = 人手动跑 graph，或人手动查看 observability 日志
```

它不在 graph 主链里，不是 node，也不参与业务决策。

## 架构位置

```text
developer / operator CLI
-> resume_query_ai_qa.scripts.run_qa
-> graph.run
-> Query-AI full pipeline
```

```text
developer / operator CLI
-> resume_query_ai_qa.scripts.query_logs
-> data/logs/query_ai/qa_runs.jsonl + data/logs/query_ai/<timestamp>_<trace_id>.json
-> human-readable run view
```

## 它做什么

- `run_qa.py`：本地手动跑一轮 Query-AI graph。
- `query_logs.py`：读取 observability 产出的日志，并渲染成列表、详情、失败、fallback/repair 视图。
- 提供调试参数，例如 `--no-llm`、`--answer-only`、`--show-trace`、`--json`。

## 它不做什么

- 不参与 graph 正常运行。
- 不作为 graph node。
- 不修改 `QueryPlan`、`ToolResult`、`AggregatedAnswer`。
- 不判断 intent、scenario、workflow 或 answer 是否正确。
- 不替代 benchmark。
- 不修复日志、plan、执行结果或答案。

## 文件职责

| 文件 | 职责 | 输入 | 输出 |
| --- | --- | --- | --- |
| `run_qa.py` | 手动运行一轮 graph | question、session context JSON、LLM 开关 | answer、trace 或完整 state JSON |
| `query_logs.py` | 浏览运行日志 | `data/logs/query_ai/qa_runs.jsonl`、detail JSON、trace_id | 人类可读文本或 JSON view |
| `__init__.py` | 包说明 | 无 | 无 |

## run_qa.py

职责：

```text
CLI 参数
-> session_context 解析
-> graph.run(...)
-> 按参数打印 answer / trace / full state
```

常用命令：

```bash
./.venv/bin/python -m resume_query_ai_qa.scripts.run_qa "谁会 Python？" --no-llm --answer-only
./.venv/bin/python -m resume_query_ai_qa.scripts.run_qa "金融候选人有几个，谁最强？" --show-trace
./.venv/bin/python -m resume_query_ai_qa.scripts.run_qa "第一名有哪些项目？" --session-context-json '{"last_ranking_candidate_ids":["c1"]}'
```

注意点：

- `--no-llm` 只影响本轮 graph 的 `use_llm=False`。
- `--answer-only` 只改变打印内容，不改变运行结果。
- `--show-trace` 打印 `state.trace`，适合看 node / route 记录。

## query_logs.py

职责：

```text
qa_runs.jsonl summary
-> trace_id
-> detail json
-> build_run_view
-> render_list / render_show
```

常用命令：

```bash
./.venv/bin/python -m resume_query_ai_qa.scripts.query_logs list --limit 5
./.venv/bin/python -m resume_query_ai_qa.scripts.query_logs show <trace_id>
./.venv/bin/python -m resume_query_ai_qa.scripts.query_logs failures --limit 5
./.venv/bin/python -m resume_query_ai_qa.scripts.query_logs fallbacks --limit 5
./.venv/bin/python -m resume_query_ai_qa.scripts.query_logs show <trace_id> --json
```

注意点：

- 只读日志，不修改日志。
- 默认读取根目录 `data/logs/query_ai/`。
- `--json` 输出的是脚本构建的 view，不是原始 detail 文件完整内容。
- 如果没有日志，会返回空列表或提示“没有匹配的 Query-AI 运行日志”。

## YAML 关系

`scripts` 自己不直接读业务 YAML 做决策。

间接关系：

- `run_qa.py` 通过 `graph.run -> load_config()` 使用全套配置。
- `query_logs.py` 不读业务 YAML，只读 observability 输出文件。
- router / planner / compiler / validator YAML 会影响 `run_qa.py` 的运行结果。
- observability 日志结构会影响 `query_logs.py` 的展示字段。

详细见 [YAML_USAGE.md](YAML_USAGE.md)。

## 是否需要优化架构

当前不建议拆文件。

理由：

- `run_qa.py` 只有一个 CLI 入口，拆分没有收益。
- `query_logs.py` 虽然较长，但职责单一：读取日志并渲染人类可读视图。
- `scripts` 是开发/运维辅助层，不在 graph 主链中；过度拆分会增加读者跳转。

## 阅读顺序

1. [README.md](README.md)
2. [SCRIPTS_FLOW.md](SCRIPTS_FLOW.md)
3. [YAML_USAGE.md](YAML_USAGE.md)
4. [run_qa.py](run_qa.py)
5. [query_logs.py](query_logs.py)
6. [../graph/README.md](../graph/README.md)
7. [../observability/README.md](../observability/README.md)

## 验收

```bash
rg "Scripts Package|SCRIPTS_FLOW|YAML_USAGE|run_qa|query_logs|build_run_view" resume_query_ai_qa/scripts
./.venv/bin/python -m compileall -q resume_query_ai_qa/scripts
./.venv/bin/python -m resume_query_ai_qa.scripts.query_logs list --limit 1
./.venv/bin/python -m resume_query_ai_qa.scripts.query_logs failures --limit 1
./.venv/bin/python -m resume_query_ai_qa.scripts.run_qa "谁会 Python？" --no-llm --answer-only
```
