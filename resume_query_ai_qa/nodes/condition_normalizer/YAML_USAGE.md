# Condition Normalizer YAML Usage

这份文档是 YAML / taxonomy 字段地图，不是流程文档。

它只回答：

```text
condition_normalizer 标准化条件时，哪些配置和数据来源会参与？
```

## 分类总览

| 来源 | 作用 | 是否本节点主流程 |
|---|---|---|
| `condition_rules.yaml` | 条件抽取、归一化、preference target 规则 | 是 |
| `shared_taxonomy/` | domain / skill / concept 的标准值、别名、检索词 | 是 |
| candidate names from data_access | 判断真实候选人姓名 | 是 |
| `condition_rules.domain_filter` | 多 domain 生成 `domains_any` 或 `domains_all` | 后续 plan_building |
| `condition_rules.cleaning.dialog_scaffolding` | 清理检索 query 里的对话脚手架词 | 后续 plan_building |
| `condition_rules.cleaning.intent_scaffolding` | 清理检索 query 里的 intent 脚手架词 | 后续 plan_building |

## condition_rules.yaml

### extraction

参与：

```text
extract_conditions(question)
```

字段：

```yaml
extraction:
  major_pattern: ...
  scopes:
    - pattern: ...
      value: ...
```

作用：

```text
major_pattern -> 抽专业 major
scopes -> 抽范围 scope，比如 项目经验 / 工作经验 / 相关经验
```

例子：

```text
计算机相关专业的人有几个？
```

输出 raw condition：

```json
{
  "type": "major",
  "raw_value": "计算机",
  "evidence": "计算机相关专业"
}
```

### preferred_type_aliases

参与：

```text
normalize_conditions(...)
```

作用：

```text
根据 QueryCondition.type 限定 taxonomy 匹配范围。
```

例子：

```json
{"type": "domain", "raw_value": "金融"}
```

会优先按 domain 匹配，而不是任意 concept/skill。

### taxonomy_alias_exclusions

参与：

```text
extract_conditions(question)
```

作用：

```text
排除 taxonomy 假阳性。
```

例子：

```text
推荐谁最适合金融岗位？
```

这里“推荐”是动作词，不是 `concept=推荐`，所以规则会排除。

### preference_target

参与：

```text
mark_preference_targets(normalized_conditions, question)
```

作用：

```text
标记“适合做什么 / 推荐谁做什么 / 按什么岗位排序”里的目标条件。
```

例子：

```text
谁最适合做金融风控？
```

`金融风控` 会被标记：

```text
matched_by = preference_target:...
```

这样后续不会把它简单当作 hard filter。

### condition_types

本节点会产出这些 type 的 normalized condition，但 `condition_types` 更多在后续使用：

```text
cleaned_retrieval_query
filter_arguments_from_conditions
```

作用：

```text
决定哪些 condition 可检索、怎么转工具参数。
```

### domain_filter

主要给后续 plan building 用。

```yaml
domain_filter:
  intersection_terms: [同时属于, 兼具, 都具备]
```

作用：

```text
多个 domain 是 domains_any 还是 domains_all。
```

例子：

```text
同时属于金融和能源的人
```

后续参数会更倾向：

```json
{"domains_all": ["金融", "能源"]}
```

### cleaning

分两类：

```text
major_prefixes -> major 抽取后清理专业名
dialog_scaffolding / intent_scaffolding -> 后续 plan_building 清理 query
```

本节点直接相关的是：

```text
major_prefixes
```

## shared_taxonomy/

参与：

```text
normalize_conditions(...)
```

提供：

```text
domain 标准值和别名
skill / concept 标准值和别名
retrieval_terms 检索扩展词
```

例子：

```text
金融风控
```

可能匹配：

```json
{
  "type": "domain",
  "normalized_value": "金融",
  "retrieval_terms": ["金融风控", "金融", "风控"]
}
```

重要边界：

```text
candidate_name 不走 shared_taxonomy。
候选人姓名来自候选人识别和 data_access。
```

## candidate names from data_access

参与：

```text
_contains_known_candidate_name(...)
```

作用：

```text
判断一个 candidate_name condition 是真实候选人，还是“第一名/这些人”这种上下文引用。
```

如果是真实候选人：

```text
保留 candidate_name
```

如果只是上下文引用：

```text
删除 candidate_name，保留 context_policy 给后续节点解析。
```

## 历史字段

```text
structured_project_tags 当前不再作为 condition_normalizer 依赖。
如果旧文档或历史 diff 里看到它，可以按历史遗留/已清理配置理解。
```

## 怎么读才不乱

建议顺序：

```text
1. condition_rules.extraction
   先看 raw conditions 怎么抽出来。

2. shared_taxonomy/
   再看 domain/skill/concept 怎么标准化。

3. condition_rules.preference_target
   看排序/推荐目标如何避免被误硬筛。

4. candidate names from data_access
   看 candidate_name 为什么不走 taxonomy。

5. domain_filter / cleaning
   记住这些更多给后续 plan_building 使用。
```
