# Data Access Package

`core/data_access/` 是 core 内部的只读底层数据访问层。

一句话：

```text
data_access = SQLite / vector index / candidate index 的只读 reader
```

它不是工具层，不直接服务 graph node；tools 和部分 rules 会间接复用这里的只读能力。

## 文件地图

| 文件 | 职责 |
| --- | --- |
| `config.py` | 读取数据访问路径和配置 |
| `sql_reader.py` | SQLite 简历结构化数据读取 |
| `vector_reader.py` | Chroma/vector 检索 reader 和 metadata 解析 |
| `candidate_index.py` | 已知候选人名列表和索引 |
| `__init__.py` | 稳定导出入口 |

## 主要联动

```text
tools/*
-> core.data_access
-> source data
```

```text
rules/candidate_mentions.py
-> candidate_index
-> known candidate names
```

```text
condition/rule helpers
-> read-only data signals
```

## 它不做什么

- 不规划工具。
- 不生成 ToolResult。
- 不写数据库。
- 不生成答案。
- 不做 validator repair。

## 排查地图

| 问题 | 看哪里 |
| --- | --- |
| SQLite 字段读取异常 | `sql_reader.py` |
| vector metadata 解析异常 | `vector_reader.py` |
| 候选人名字索引异常 | `candidate_index.py` |
| 数据路径不对 | `config.py` |
