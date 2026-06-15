# LLM Client Package

`core/llm/client/` 是 LLM provider 和 structured invoke 的实现层。

一句话：

```text
client = config -> provider model -> structured response -> schema payload cleanup
```

## 文件地图

| 文件 | 职责 |
| --- | --- |
| `settings.py` | 从 `ResumeQAConfig.llm` 读取 provider/model/timeout 等值 |
| `models.py` | 构造 ChatModel，判断 LLM 是否启用 |
| `structured.py` | 统一 structured invoke 入口 |
| `ollama_json.py` | Ollama JSON mode fallback |
| `payload_normalization.py` | LLM JSON shape cleanup |
| `schema_contracts.py` | 紧凑 schema contract 文本 |
| `errors.py` | LLM 异常类型 |
| `__init__.py` | 公开 API |

## 主流程

```text
invoke_structured(schema, prompt, config)
-> is_llm_enabled / build_chat_model
-> provider invoke
-> payload normalization
-> schema.model_validate
```

Ollama schema 不稳定时：

```text
structured.py
-> ollama_json.py
-> parse_json_object
-> normalize_schema_payload
-> schema validate
```

## 边界

这里可以：

- 读 `llm.yaml` / env 后的 config。
- 构造 provider model。
- 清理 JSON payload shape。
- 抛 `ResumeQALLMError`。

这里不可以：

- 判断业务 intent。
- 选择工具。
- 调用 tool registry。
- 修复 QueryPlan。
- 判断答案事实是否可靠。

## 排查地图

| 问题 | 看哪里 |
| --- | --- |
| provider/model 没启用 | `settings.py`、`models.py` |
| structured invoke 报错 | `structured.py` |
| Ollama JSON 格式不稳 | `ollama_json.py` |
| LLM JSON 字段 shape 不对 | `payload_normalization.py` |
| prompt schema 太长/不清楚 | `schema_contracts.py` |
