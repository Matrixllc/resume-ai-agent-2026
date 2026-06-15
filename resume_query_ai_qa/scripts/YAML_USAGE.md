# Scripts YAML Usage

`scripts` 自己不直接读取业务 YAML 做决策。

它们是 CLI 包装层：

```text
run_qa.py      -> 间接触发 graph/config
query_logs.py  -> 只读 observability 日志文件
```

## 1. run_qa.py

直接做的事：

```text
parse CLI args
parse session_context JSON
call graph.run(...)
print result
```

间接 YAML 使用：

```text
graph.run
-> load_config
-> configs/*.yaml
```

也就是说，以下 YAML 会影响 `run_qa.py` 跑出来的结果，但不是 `run_qa.py` 自己读取：

```text
intents.yaml
router_rules.yaml
condition_rules.yaml
scenarios.yaml
tool_policy.yaml
compiler_templates.yaml
validation.yaml
answer_layouts.yaml
aggregator_tasks.yaml
evidence_policy.yaml
jd_scoring.yaml
```

`.env` / LLM provider 也通过 graph/config 间接影响：

```text
--no-llm
  -> use_llm=False
  -> 禁用本轮 LLM 路径

不加 --no-llm
  -> use_llm=True
  -> 具体能不能调用 LLM 取决于配置和环境变量
```

## 2. query_logs.py

直接读取：

```text
data/logs/query_ai/qa_runs.jsonl
data/logs/query_ai/<timestamp>_<trace_id>.json
```

不读取：

```text
configs/*.yaml
.env
tool_policy.yaml
validation.yaml
answer_layouts.yaml
```

它依赖的是 observability 输出结构，而不是业务 YAML。

如果 `query_logs.py` 显示字段缺失，优先检查：

```text
observability/logging.py
state/trace.py
data/logs/query_ai/<timestamp>_<trace_id>.json
```

## 3. 和 Observability 的关系

`observability` 写日志：

```text
write_run_log
-> qa_runs.jsonl
-> detail json
```

`query_logs.py` 读日志：

```text
load_run_summaries
-> find_detail
-> build_run_view
-> render_list / render_show
```

所以 `query_logs.py` 的稳定性取决于：

```text
run_summary 字段
decision_log 字段
route_events 字段
final_answer 字段
failed_at 字段
```

## 4. 快速区分

| 文件 | 是否直接读 YAML | YAML 如何影响它 |
| --- | --- | --- |
| `run_qa.py` | 否 | 通过 `graph.run -> load_config()` 间接影响运行结果 |
| `query_logs.py` | 否 | 不影响；它只读已经落盘的日志 |

## 5. 注意点

- 不要在 scripts 里新增业务规则判断。
- 不要让 `query_logs.py` 重新解释 intent / plan / answer。
- 不要把 benchmark 逻辑搬进 scripts。
- 如果需要稳定回归测试，继续放在 `benchmarks/`。
