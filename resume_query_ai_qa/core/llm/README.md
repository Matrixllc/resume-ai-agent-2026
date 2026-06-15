# LLM Package

`core/llm/` 是 Query-AI 自己的 LLM 客户端和 prompt 合同层。

一句话：

```text
llm = provider setup + structured invoke + prompt/schema contracts
```

它可以调用配置好的 LLM provider，但不能调用 tools、graph 或 nodes。

## 文件地图

| 文件 | 职责 |
| --- | --- |
| `prompts.py` | router/planner/answer 相关 prompt helper 和 tool spec 摘要 |
| `client/` | provider、structured invoke、schema contract、payload normalization |
| `__init__.py` | 稳定公开 API |

## 主要联动

```text
nodes/router/llm.py
-> core.llm.invoke_structured
```

```text
nodes/planner/llm.py
-> core.llm.invoke_structured
```

```text
core.answer_generation.llm
-> core.llm.invoke_structured
```

## 不变量

- LLM 输出只是 draft。
- draft 必须经过 Pydantic schema 校验。
- router 有 guard/finalizer。
- planner 有 normalize_semantic_plan。
- answer 有 fact drift / layout rejection / answer_validator。

## 它不做什么

- 不选择工具链。
- 不执行工具。
- 不修复 plan。
- 不把 LLM 文本直接视为事实。

## 阅读顺序

1. [README.md](README.md)
2. [client/README.md](client/README.md)
3. `prompts.py`
4. `client/models.py`
5. `client/structured.py`
6. `client/payload_normalization.py`
7. `client/schema_contracts.py`
