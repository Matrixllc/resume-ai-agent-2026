# Scripts Flow

这份文档讲 `resume_query_ai_qa/scripts/` 的两个 CLI 怎么读。  
它们是本地入口，不是 graph node。

## 1. 总览

```text
run_qa.py
  人手动输入 question
  -> graph.run
  -> 打印 answer / trace / full state
```

```text
query_logs.py
  人手动查询 logs
  -> 读取 qa_runs.jsonl 和 detail json
  -> 构建 run view
  -> 打印 list / show / failures / fallbacks
```

## 2. run_qa.py 阅读线

入口：

```text
main()
```

执行顺序：

```text
main
-> argparse.ArgumentParser
-> _parse_session_context
-> graph.run(question, session_context, use_llm)
-> print trace / answer / debug JSON / full state
```

参数含义：

| 参数 | 作用 |
| --- | --- |
| `question` | 送入 Query-AI graph 的用户问题 |
| `--session-context-json` | 上一轮上下文，必须是 JSON object |
| `--answer-only` | 只打印最终答案文本 |
| `--no-llm` | 本轮禁用 LLM，走确定性规则路径 |
| `--debug-json` | 打印完整 state JSON |
| `--show-trace` | 只打印 `state.trace` |

输出分支：

```text
--show-trace
  -> state.trace.model_dump_json(...)

--answer-only
  -> state.answer.answer

--debug-json
  -> state.model_dump_json(...)

default
  -> state.model_dump_json(...)
```

## 3. run_qa.py 示例

只看答案：

```bash
./.venv/bin/python -m resume_query_ai_qa.scripts.run_qa "谁会 Python？" --no-llm --answer-only
```

看 trace：

```bash
./.venv/bin/python -m resume_query_ai_qa.scripts.run_qa "金融候选人有几个，谁最强？" --show-trace
```

带上下文追问：

```bash
./.venv/bin/python -m resume_query_ai_qa.scripts.run_qa "第一名有哪些项目？" --session-context-json '{"last_ranking_candidate_ids":["candidate_001"]}'
```

## 4. query_logs.py 阅读线

入口：

```text
main()
```

执行顺序：

```text
main
-> _build_parser
-> command dispatch
-> list_views / find_detail
-> build_run_view
-> render_list / render_show
```

命令：

| command | 作用 |
| --- | --- |
| `list` | 最近运行列表 |
| `show <trace_id>` | 展示单轮运行详情 |
| `failures` | 只看 failed / needs_clarification |
| `fallbacks` | 只看发生 fallback 或 repair 的运行 |

## 5. 日志浏览流程

```text
load_run_summaries
-> data/logs/query_ai/qa_runs.jsonl
-> summary rows
```

```text
find_detail(trace_id)
-> data/logs/query_ai/*_<trace_id>.json
-> detail
```

```text
build_run_view(summary, detail)
-> timeline
-> fallbacks
-> repairs
-> validator_errors
-> warnings
-> answer
-> suggested_check
```

```text
render_list / render_show
-> human-readable text
```

如果加 `--json`：

```text
view dict/list
-> json.dumps(...)
```

## 6. build_run_view 做了什么

输入：

```text
summary from qa_runs.jsonl
detail from <timestamp>_<trace_id>.json
```

输出：

```text
trace_id
created_at
question
status
intent
duration_ms
path
tools
warnings
fallbacks
repairs
validator_errors
failed_node
failed_reason
answer
what_happened
system_handling
impact
suggested_check
```

它不重新判断业务对错，只把已有日志整理成人更容易读的视图。

## 7. 排查路径

想复现问题：

```text
run_qa.py
```

想看最近跑过什么：

```text
query_logs.py list
```

想看历史失败：

```text
query_logs.py failures
```

想看 fallback / repair：

```text
query_logs.py fallbacks
```

想接入脚本或工具消费：

```text
query_logs.py ... --json
```

## 8. 边界提醒

`scripts` 是人工调试入口。

如果问题是：

- CLI 参数解析错：看 `run_qa.py` / `query_logs.py`
- graph 行为错：看 `graph/` 和 `nodes/`
- 日志没有写出：看 `observability/`
- trace 字段缺失：看 `state/trace.py`
- benchmark 不过：看 `benchmarks/`
